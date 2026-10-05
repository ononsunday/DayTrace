"""交付文件夹与源码 ZIP；只复制白名单，不打包本地使用记录。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def licensed_files():
    base = ROOT / "third_party_licenses"
    manifest = json.loads((base / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    result = []
    for entry in manifest:
        file = (base / entry["file"]).resolve()
        if not file.is_relative_to(base.resolve()):
            raise ValueError("许可证清单含越界路径")
        if hashlib.sha256(file.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"许可证校验失败：{entry['file']}")
        result.append(file)
    result.append(base / "SOURCE_MANIFEST.json")
    return result


def source_files():
    files = [ROOT / name for name in ("README.md", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "run_daytrace.py", "运行源码.cmd", "DayTrace.spec", ".gitignore", "THIRD_PARTY_NOTICES.md", "LICENSE", "CONTRIBUTING.md", "CHANGELOG.md", ".gitattributes")]
    for directory in ("daytrace", "tests", "scripts", "docs", "assets", ".github"):
        for file in (ROOT / directory).rglob("*"):
            if file.is_file() and not {"__pycache__", "design-references"}.intersection(file.parts) and not file.name.endswith((".pyc", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite-wal", ".sqlite-shm", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".log")):
                files.append(file)
    return files + licensed_files()


def deliver(destination):
    if destination.exists():
        raise ValueError("交付目录已存在；请指定新的目录，避免覆盖已有文件")
    runtime = ROOT / "dist" / "DayTrace"
    if not (runtime / "DayTrace.exe").is_file():
        raise ValueError("请先运行 scripts/build.ps1")
    files = source_files()
    for file in files:
        if not file.is_file():
            raise ValueError(f"缺少交付文件：{file}")
    shutil.copytree(runtime, destination)
    guide = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = guide.replace("(docs/Windows运行与验收.md)", "(Windows运行与验收.md)").replace("(docs/验证报告.md)", "(验证报告.md)")
    (destination / "使用说明.md").write_text(guide, encoding="utf-8")
    shutil.copy2(ROOT / "docs" / "验证报告.md", destination / "验证报告.md")
    shutil.copy2(ROOT / "docs" / "Windows运行与验收.md", destination / "Windows运行与验收.md")
    legacy_report = ROOT / "docs" / "验证报告-1.0.0.md"
    if legacy_report.is_file():
        shutil.copy2(legacy_report, destination / legacy_report.name)
    preview = ROOT / "docs" / "界面预览.png"
    if preview.is_file():
        shutil.copy2(preview, destination / "界面预览.png")
    if (ROOT / "docs" / "验证记录").is_dir():
        shutil.copytree(ROOT / "docs" / "验证记录", destination / "验证记录")
    shutil.copy2(ROOT / "LICENSE", destination / "LICENSE")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", destination / "THIRD_PARTY_NOTICES.md")
    for file in licensed_files():
        target = destination / file.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
    archive = destination / "DayTrace-源码.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for file in files:
            output.write(file, "DayTrace/" + file.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as output:
        if output.testzip() is not None:
            raise ValueError("源码 ZIP 完整性校验失败")
        names = output.namelist()
        if any(".venv/" in name or "qa-output/" in name or "__pycache__/" in name or name.endswith((".db", ".sqlite3", ".log")) for name in names):
            raise ValueError("源码 ZIP 意外包含临时或用户数据")
    executable_hash = hashlib.sha256((destination / "DayTrace.exe").read_bytes()).hexdigest()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    report = {"product": "DayTrace", "version": version, "executable_sha256": executable_hash,
              "source_zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
              "source_entries": len(names), "personal_data_included": False,
              "files": sum(f.is_file() for f in destination.rglob("*")) + 1, "bytes": 0}
    other_bytes = sum(f.stat().st_size for f in destination.rglob("*") if f.is_file())
    while True:
        encoded = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        total = other_bytes + len(encoded)
        if report["bytes"] == total:
            break
        report["bytes"] = total
    (destination / "交付校验.json").write_bytes(encoded)
    print(json.dumps({"destination": str(destination), **report}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=ROOT / "dist" / "DayTrace-release")
    args = parser.parse_args()
    deliver(args.destination.resolve())
