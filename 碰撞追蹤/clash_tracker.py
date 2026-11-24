"""Navisworks Clash Detective 匯出 → 站別／系統／處理狀態 追蹤表.

輸入 (擇一或多個):
  * Navisworks「Clash Detective > 報告 > XML」匯出的 .xml
  * NavisworksPlugin 匯出的 .csv (欄位名同 ClashRow)
輸出:
  * 追蹤表 .xlsx (明細 / 摘要)，並保留舊表人工填寫欄位
  * 同名 .csv (UTF-8 BOM, 供 Power BI)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

CONFIG_PATH = Path(__file__).with_name("clash_config.json")

COLUMNS = [
    "碰撞ID", "測試名稱", "碰撞名稱", "站別", "系統A", "系統B", "系統組合",
    "Navisworks狀態", "處理狀態", "距離", "網格位置",
    "X", "Y", "Z", "物件A", "物件B", "檔案A", "檔案B",
    "指派給", "核可者", "核可時間", "建立時間", "說明",
]


@dataclass
class ClashRow:
    guid: str = ""
    test: str = ""
    name: str = ""
    status: str = ""
    distance: Optional[float] = None
    grid: str = ""
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    item_a: str = ""
    item_b: str = ""
    file_a: str = ""
    file_b: str = ""
    path_a: str = ""
    path_b: str = ""
    assigned_to: str = ""
    approved_by: str = ""
    approved_time: str = ""
    created: str = ""
    description: str = ""


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- parsing
def _txt(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def _float(v: Optional[str]) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _date(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    d = el.find("date")
    if d is None:
        return _txt(el)
    a = d.attrib
    try:
        return "%04d-%02d-%02d %02d:%02d:%02d" % tuple(
            int(a.get(k, 0)) for k in ("year", "month", "day", "hour", "minute", "second"))
    except ValueError:
        return ""


_EMPTY_OBJ = {"name": "", "file": "", "path": ""}


def _object(co: ET.Element) -> Dict[str, str]:
    nodes = [_txt(n) for n in co.findall("./pathlink/node")]
    name = ""
    for attr in co.iter("objectattribute"):
        if _txt(attr.find("name")) in ("Item Name", "名稱", "項目名稱"):
            name = _txt(attr.find("value"))
            break
    if not name and nodes:
        name = nodes[-1]
    file_ = next((n for n in nodes if re.search(r"\.(nwd|nwc|rvt|dwg|ifc)\b", n, re.I)),
                 nodes[0] if nodes else "")
    return {"name": name, "file": file_, "path": " > ".join(nodes)}


def parse_xml(path: Path) -> List[ClashRow]:
    root = ET.parse(path).getroot()
    rows: List[ClashRow] = []
    for test in root.iter("clashtest"):
        for res in test.iter("clashresult"):
            objs = [_object(o) for o in res.iter("clashobject")]
            a = objs[0] if len(objs) > 0 else _EMPTY_OBJ
            b = objs[1] if len(objs) > 1 else _EMPTY_OBJ
            pos = res.find("./clashpoint/pos3f")
            rows.append(ClashRow(
                guid=res.get("guid", ""), test=test.get("name", ""), name=res.get("name", ""),
                status=res.get("status", ""), distance=_float(res.get("distance")),
                grid=_txt(res.find("gridlocation")),
                x=_float(pos.get("x")) if pos is not None else None,
                y=_float(pos.get("y")) if pos is not None else None,
                z=_float(pos.get("z")) if pos is not None else None,
                item_a=a["name"], item_b=b["name"], file_a=a["file"], file_b=b["file"],
                path_a=a["path"], path_b=b["path"],
                assigned_to=_txt(res.find("assignedto")),
                approved_by=_txt(res.find("approvedby")),
                approved_time=_date(res.find("approvedtime")),
                created=_date(res.find("createddate")),
                description=_txt(res.find("description")),
            ))
    return rows


_NUM = {"distance", "x", "y", "z"}


def parse_csv(path: Path) -> List[ClashRow]:
    fields = ClashRow.__dataclass_fields__
    rows: List[ClashRow] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for rec in csv.DictReader(fh):
            kw: Dict[str, Any] = {}
            for k in fields:
                v = (rec.get(k) or "").strip()
                kw[k] = _float(v) if k in _NUM else v
            rows.append(ClashRow(**kw))
    return rows


def load_rows(paths: Iterable[Path]) -> List[ClashRow]:
    rows: List[ClashRow] = []
    for p in paths:
        suf = p.suffix.lower()
        if suf == ".xml":
            rows += parse_xml(p)
        elif suf == ".csv":
            rows += parse_csv(p)
        else:
            raise ValueError(f"不支援的格式: {p}")
    return rows


# ---------------------------------------------------------- classification
def _match_rules(text: str, rules: List[Dict[str, Any]], default: str) -> str:
    for r in rules:
        m = re.search(r["pattern"], text, re.I)
        if m:
            return m.group(0).upper() if r.get("use_match") else r["value"]
    return default


def classify_station(row: ClashRow, cfg: Dict[str, Any]) -> str:
    text = " ".join([row.test, row.file_a, row.file_b, row.path_a, row.path_b, row.name])
    return _match_rules(text, cfg["station_rules"], cfg["station_default"])


def classify_system(file_name: str, path: str, item: str, cfg: Dict[str, Any]) -> str:
    # 檔名優先 (模型分專業)，再看路徑與物件名稱
    for text in (file_name, path, item):
        v = _match_rules(text, cfg["system_rules"], "")
        if v:
            return v
    return cfg["system_default"]


def map_status(raw: str, cfg: Dict[str, Any]) -> str:
    return cfg["status_map"].get((raw or "").strip().lower(), raw or "未知")


def build_records(rows: List[ClashRow], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        sa = classify_system(r.file_a, r.path_a, r.item_a, cfg)
        sb = classify_system(r.file_b, r.path_b, r.item_b, cfg)
        out.append({
            "碰撞ID": r.guid or f"{r.test}|{r.name}", "測試名稱": r.test, "碰撞名稱": r.name,
            "站別": classify_station(r, cfg), "系統A": sa, "系統B": sb,
            "系統組合": f"{sa} 內部" if sa == sb else " × ".join(sorted((sa, sb))),
            "Navisworks狀態": r.status, "處理狀態": map_status(r.status, cfg),
            "距離": r.distance, "網格位置": r.grid, "X": r.x, "Y": r.y, "Z": r.z,
            "物件A": r.item_a, "物件B": r.item_b, "檔案A": r.file_a, "檔案B": r.file_b,
            "指派給": r.assigned_to, "核可者": r.approved_by, "核可時間": r.approved_time,
            "建立時間": r.created, "說明": r.description,
        })
    return out


# --------------------------------------------------------------- carry-over
def read_manual(xlsx: Path, cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """從舊追蹤表讀回人工欄位 (負責人/送審狀態/備註)，以碰撞ID 為鍵."""
    from openpyxl import load_workbook
    if not xlsx.exists():
        return {}
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    try:
        it = wb["明細"].iter_rows(values_only=True)
        header = list(next(it, []))
        if "碰撞ID" not in header:
            return {}
        idx = header.index("碰撞ID")
        cols = {c: header.index(c) for c in cfg["manual_columns"] if c in header}
        return {str(r[idx]): {c: r[i] for c, i in cols.items()} for r in it if r[idx]}
    finally:
        wb.close()


def apply_manual(records: List[Dict[str, Any]], manual: Dict[str, Dict[str, Any]],
                 cfg: Dict[str, Any]) -> None:
    for rec in records:
        old = manual.get(rec["碰撞ID"], {})
        for c in cfg["manual_columns"]:
            rec[c] = old.get(c) or ""


# ------------------------------------------------------------------ summary
def summarize(records: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[List[Any]]:
    statuses = list(cfg["status_map"].values())
    open_set = set(cfg["open_statuses"])
    groups: Dict[tuple, Dict[str, int]] = {}
    for r in records:
        g = groups.setdefault((r["站別"], r["系統組合"]), {})
        g[r["處理狀態"]] = g.get(r["處理狀態"], 0) + 1
    table: List[List[Any]] = [["站別", "系統組合", *statuses, "合計", "未結案"]]
    for (st, sy), g in sorted(groups.items()):
        table.append([st, sy, *[g.get(s, 0) for s in statuses], sum(g.values()),
                      sum(v for k, v in g.items() if k in open_set)])
    return table


def write_outputs(records: List[Dict[str, Any]], out: Path, cfg: Dict[str, Any]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    cols = COLUMNS + cfg["manual_columns"]
    wb = Workbook()
    ws = wb.active
    ws.title = "明細"
    ws.append(cols)
    for r in records:
        ws.append([r.get(c) for c in cols])
    hdr = PatternFill("solid", fgColor="1F4E78")
    manual = PatternFill("solid", fgColor="BF8F00")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = manual if cell.value in cfg["manual_columns"] else hdr
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        width = max(len(str(c.value or "")) for c in col[:50])
        ws.column_dimensions[col[0].column_letter].width = min(40, max(10, width + 2))

    sm = wb.create_sheet("摘要")
    for row in summarize(records, cfg):
        sm.append(row)
    for cell in sm[1]:
        cell.font = Font(bold=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(out)
    with open(out.with_suffix(".csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in records:
            w.writerow(["" if r.get(c) is None else r[c] for c in cols])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Navisworks 碰撞 → 追蹤表")
    ap.add_argument("inputs", nargs="+", type=Path, help="Clash XML / CSV")
    ap.add_argument("-o", "--output", type=Path, default=Path("碰撞追蹤表.xlsx"))
    ap.add_argument("-c", "--config", type=Path, default=None)
    ap.add_argument("--no-carry", action="store_true", help="不從既有輸出檔帶回人工欄位")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    try:
        rows = load_rows(a.inputs)
        records = build_records(rows, cfg)
        apply_manual(records, {} if a.no_carry else read_manual(a.output, cfg), cfg)
        write_outputs(records, a.output, cfg)
    except (OSError, ET.ParseError, ValueError) as e:
        print(f"失敗: {e}", file=sys.stderr)
        return 1
    open_n = sum(1 for r in records if r["處理狀態"] in cfg["open_statuses"])
    print(f"{len(records)} 筆碰撞，未結案 {open_n} → {a.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
