"""一键生成 4 类 Wind 取数模板。

执行:
    python scripts/make_templates_all.py

只生成 4 类频率模板 (成员/universe 走 import_membership.py, 不调 Wind):
    static -> daily -> annual -> financials(年报+半年报全科目)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
SCRIPTS = [
    ROOT / "scripts" / "make_template_info.py",
    ROOT / "scripts" / "make_template_daily.py",
    ROOT / "scripts" / "make_template_annual.py",
    ROOT / "scripts" / "make_template_financials.py",
]


def main() -> int:
    print("🚀 Start building all Wind templates")
    for script in SCRIPTS:
        print(f"\n▶ {script.name}")
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT)
        if result.returncode != 0:
            print(f"❌ Failed: {script.name}")
            return result.returncode
    print("\n✅ All templates are generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
