import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clash_tracker as ct  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

XML = """<?xml version="1.0" encoding="UTF-8"?>
<exchange><batchtest name="B"><clashtests>
<clashtest name="SB12 電力 vs 空調">
 <clashresults>
  <clashresult name="Clash1" guid="g-1" status="new" distance="-0.05">
   <description>Hard</description><gridlocation>A-1 : L1</gridlocation>
   <clashpoint><pos3f x="1.5" y="2.5" z="3.5"/></clashpoint>
   <createddate><date year="2026" month="11" day="2" hour="9" minute="5" second="0"/></createddate>
   <clashobjects>
    <clashobject><pathlink><node>SB12_EL_Model.rvt</node><node>Tray</node></pathlink>
      <objectattribute><name>Item Name</name><value>Tray-1</value></objectattribute></clashobject>
    <clashobject><pathlink><node>SB12_ME_Model.rvt</node><node>Duct</node></pathlink></clashobject>
   </clashobjects>
  </clashresult>
  <clashresult name="Clash2" guid="g-2" status="approved" distance="-0.01">
   <clashobjects>
    <clashobject><pathlink><node>SB12_ST_Model.rvt</node></pathlink></clashobject>
    <clashobject><pathlink><node>SB12_ST_Model.rvt</node></pathlink></clashobject>
   </clashobjects>
  </clashresult>
 </clashresults></clashtest></clashtests></batchtest></exchange>"""


def _write(tmp_path):
    x = tmp_path / "c.xml"
    x.write_text(XML, encoding="utf-8")
    return x


def test_classification(tmp_path):
    cfg = ct.load_config()
    rec = ct.build_records(ct.parse_xml(_write(tmp_path)), cfg)
    assert rec[0]["站別"] == "SB12"
    assert (rec[0]["系統A"], rec[0]["系統B"]) == ("電力", "空調")
    assert rec[0]["處理狀態"] == "待處理" and rec[0]["Z"] == 3.5
    assert rec[0]["建立時間"] == "2026-11-02 09:05:00"
    assert rec[1]["系統組合"] == "結構 內部" and rec[1]["處理狀態"] == "已核可"


def test_manual_columns_carry_over(tmp_path):
    out = tmp_path / "t.xlsx"
    x = _write(tmp_path)
    assert ct.main([str(x), "-o", str(out)]) == 0
    wb = load_workbook(out)
    ws = wb["明細"]
    h = [c.value for c in ws[1]]
    ws.cell(2, h.index("備註") + 1, "待機電確認")
    wb.save(out)
    assert ct.main([str(x), "-o", str(out)]) == 0
    ws = load_workbook(out)["明細"]
    assert ws.cell(2, h.index("備註") + 1).value == "待機電確認"
    assert out.with_suffix(".csv").exists()


def test_csv_roundtrip(tmp_path):
    out = tmp_path / "t.xlsx"
    assert ct.main([str(_write(tmp_path)), "-o", str(out)]) == 0
    # 外掛 CSV (欄位名同 ClashRow)
    c = tmp_path / "p.csv"
    c.write_text("guid,test,name,status,file_a,file_b,x\ng-9,SB14 T,C9,active,"
                 "SB14_EL.rvt,SB14_PL.rvt,1\n", encoding="utf-8-sig")
    rows = ct.parse_csv(c)
    rec = ct.build_records(rows, ct.load_config())[0]
    assert rec["站別"] == "SB14" and rec["處理狀態"] == "處理中" and rec["X"] == 1.0


def test_summary_counts(tmp_path):
    cfg = ct.load_config()
    rec = ct.build_records(ct.parse_xml(_write(tmp_path)), cfg)
    t = ct.summarize(rec, cfg)
    assert t[0][-2:] == ["合計", "未結案"]
    assert sum(r[-1] for r in t[1:]) == 1


def test_bad_file(tmp_path):
    bad = tmp_path / "b.xml"
    bad.write_text("<x", encoding="utf-8")
    assert ct.main([str(bad), "-o", str(tmp_path / "o.xlsx")]) == 1
