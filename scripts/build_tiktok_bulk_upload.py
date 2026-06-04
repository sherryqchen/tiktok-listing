#!/usr/bin/env python3
"""Fill a TikTok Shop bulk upload template from structured listing data.

This keeps the official TikTok workbook structure intact and only rewrites
the product rows on the Template sheet.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("", NS_MAIN)


def q(tag: str) -> str:
    return f"{{{NS_MAIN}}}{tag}"


def column_name(index: int) -> str:
    out = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        out = chr(65 + remainder) + out
    return out


def column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        raise ValueError(f"Invalid cell reference: {cell_ref}")
    number = 0
    for char in match.group(1):
        number = number * 26 + ord(char) - 64
    return number


def cell_ref(col_index: int, row_index: int) -> str:
    return f"{column_name(col_index)}{row_index}"


def retarget_cell(cell: ET.Element, row_index: int) -> None:
    ref = cell.attrib.get("r")
    if not ref:
        return
    cell.attrib["r"] = f"{re.match(r'[A-Z]+', ref).group(0)}{row_index}"


def retarget_row(row: ET.Element, row_index: int) -> ET.Element:
    new_row = copy.deepcopy(row)
    new_row.attrib["r"] = str(row_index)
    for cell in new_row.findall(q("c")):
        retarget_cell(cell, row_index)
    return new_row


def set_cell_text(cell: ET.Element, value: object) -> None:
    for child in list(cell):
        cell.remove(child)
    if value is None or value == "":
        cell.attrib.pop("t", None)
        return
    cell.attrib["t"] = "inlineStr"
    inline = ET.SubElement(cell, q("is"))
    text = ET.SubElement(inline, q("t"))
    text.text = str(value)
    if "\n" in text.text or text.text.startswith(" ") or text.text.endswith(" "):
        text.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"


def find_template_sheet_path(xlsx_path: Path) -> str:
    with zipfile.ZipFile(xlsx_path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        for sheet in workbook.findall(f".//{{{NS_MAIN}}}sheet"):
            if sheet.attrib.get("name") == "Template":
                rel_id = sheet.attrib[f"{{{NS_REL}}}id"]
                target = rel_map[rel_id]
                return f"xl/{target}".replace("xl//", "xl/")
    raise RuntimeError("Could not find a sheet named Template in the workbook.")


def build_rows(config: dict) -> list[dict[str, object]]:
    listing = config["listing"]
    attrs = listing["attributes"]
    images = listing["images"]
    rows = []
    for sku in config["skus"]:
        is_print = sku["type"].lower().startswith("print")
        material = attrs["material_print"] if is_print else attrs["material_canvas"]
        row = {
            "A": listing["category"],
            "B": listing["brand"],
            "C": listing["product_name"],
            "D": listing["product_description"],
            "E": images.get("main_image", ""),
            "F": images.get("image_2", ""),
            "G": images.get("image_3", ""),
            "H": images.get("image_4", ""),
            "I": images.get("image_5", ""),
            "P": listing["variation_1_name"],
            "Q": sku["type"],
            "AA": listing["variation_2_name"],
            "AB": sku["size"],
            "AC": sku["weight_lb"],
            "AD": sku["length_in"],
            "AE": sku["width_in"],
            "AF": sku["height_in"],
            "AG": listing["delivery"],
            "AH": f"{sku['price']:.2f}",
            "AJ": listing["warehouse_quantity_1"],
            "AK": listing["warehouse_quantity_2"],
            "AL": sku["seller_sku"],
            "AP": attrs["pattern"],
            "AQ": attrs["occasion"],
            "AR": attrs["style"],
            "AS": attrs["feature"],
            "AT": attrs["shape"],
            "AV": material,
            "AW": attrs["setting"],
            "AX": attrs["use"],
            "AY": attrs["installment"],
            "AZ": attrs["dangerous_goods"],
            "BA": attrs["other_dangerous_goods"],
            "BB": attrs["ca_prop65_repro_chems"],
            "BC": attrs["reprotoxic_chemicals"],
            "BD": attrs["ca_prop65_carcinogens"],
            "BE": attrs["carcinogen"],
            "BH": listing["status"],
        }
        rows.append(row)
    return rows


def rewrite_template_sheet(sheet_path: Path, rows_to_write: list[dict[str, object]]) -> None:
    tree = ET.parse(sheet_path)
    root = tree.getroot()
    sheet_data = root.find(q("sheetData"))
    if sheet_data is None:
        raise RuntimeError("Template sheet has no sheetData.")

    existing_rows = list(sheet_data.findall(q("row")))
    row_6 = next((row for row in existing_rows if row.attrib.get("r") == "6"), None)
    if row_6 is None:
        raise RuntimeError("Template sheet has no row 6 to use as the product-row style source.")

    product_start = 6
    product_end = product_start + len(rows_to_write) - 1
    for row in existing_rows:
        row_number = int(row.attrib.get("r", "0"))
        if product_start <= row_number <= product_end:
            sheet_data.remove(row)

    insert_after_index = 0
    for index, row in enumerate(list(sheet_data.findall(q("row")))):
        if int(row.attrib.get("r", "0")) < product_start:
            insert_after_index = index + 1

    new_rows = []
    for offset, row_values in enumerate(rows_to_write):
        row_index = product_start + offset
        new_row = retarget_row(row_6, row_index)
        cells_by_col = {
            re.match(r"[A-Z]+", cell.attrib["r"]).group(0): cell
            for cell in new_row.findall(q("c"))
        }
        for col_index in range(1, 61):
            col = column_name(col_index)
            cell = cells_by_col.get(col)
            if cell is None:
                cell = ET.SubElement(new_row, q("c"), {"r": cell_ref(col_index, row_index), "s": "45"})
                cells_by_col[col] = cell
            set_cell_text(cell, row_values.get(col, ""))
        new_row[:] = sorted(new_row.findall(q("c")), key=lambda c: column_index(c.attrib["r"]))
        new_rows.append(new_row)

    for offset, row in enumerate(new_rows):
        sheet_data.insert(insert_after_index + offset, row)

    dimension = root.find(q("dimension"))
    if dimension is not None:
        dimension.attrib["ref"] = f"A1:BH{max(product_end, 6)}"

    tree.write(sheet_path, encoding="UTF-8", xml_declaration=True)


def copy_and_unpack_template(template_path: Path, workdir: Path) -> None:
    with zipfile.ZipFile(template_path) as archive:
        archive.extractall(workdir)


def repack_xlsx(workdir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(workdir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(workdir).as_posix())


def validate_config(config: dict) -> list[str]:
    warnings = []
    images = config["listing"].get("images", {})
    for key, value in images.items():
        if "example.com/replace" in value:
            warnings.append(f"{key} is still a placeholder image URL: {value}")
    if config["listing"].get("brand") == "INKERASTORY":
        warnings.append("Brand INKERASTORY must exist/validate in TikTok Seller Center; this template only listed No brand.")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate TikTok Shop bulk upload XLSX.")
    parser.add_argument("--config", default="data/inkerastory_listing.json", help="Listing config JSON path.")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    template_path = Path(config["template_path"])
    output_path = Path(config["output_path"])
    rows_to_write = build_rows(config)

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        copy_and_unpack_template(template_path, workdir)
        sheet_rel_path = find_template_sheet_path(template_path)
        rewrite_template_sheet(workdir / sheet_rel_path, rows_to_write)
        repack_xlsx(workdir, output_path)

    print(f"Wrote {len(rows_to_write)} SKU rows to {output_path}")
    warnings = validate_config(config)
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
