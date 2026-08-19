import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools" / "architecture"))

from typescript_analyzer import analyze_typescript


def type_entry(path: str, symbol: str, owner: str = "ui") -> dict:
    return {
        "id": symbol.casefold(),
        "language": "typescript",
        "owner": owner,
        "declaration": {"path": path, "symbol": symbol, "kind": "interface"},
    }


class TypeScriptAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        compiler = PROJECT_ROOT / "frontend" / "node_modules" / "typescript"
        destination = self.root / "frontend" / "node_modules"
        destination.mkdir(parents=True)
        (destination / "typescript").symlink_to(compiler, target_is_directory=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def manifest(self, *, types: list[dict] | None = None, public_symbols: list[dict] | None = None) -> dict:
        return {
            "source_sets": [{"id": "production", "classification": "production", "include": ["src/**"], "exclude": []}],
            "modules": [
                {"id": "ui", "paths": ["src"], "public_symbols": public_symbols or []},
                {"id": "other", "paths": ["other"], "public_symbols": []},
            ],
            "types": types or [],
        }

    def write(self, source: str, name: str = "model.ts") -> str:
        path = self.root / "src" / name
        path.write_text(source, encoding="utf-8")
        return path.relative_to(self.root).as_posix()

    def rules(self, manifest: dict) -> tuple[set[str], dict]:
        diagnostics, evidence = analyze_typescript(manifest, self.root)
        return {item["rule_id"] for item in diagnostics}, evidence

    def test_compiler_api_catalogs_ts_and_tsx_types_and_public_symbols(self) -> None:
        ts_path = self.write("interface Alpha {}\ntype Beta = string;\nclass Gamma {}\nenum Delta { One }\nexport function make() {}")
        tsx_path = self.write("export interface Props { title: string }\nexport const View = (props: Props) => <div>{props.title}</div>;", "View.tsx")
        entries = [type_entry(ts_path, symbol) for symbol in ("Alpha", "Beta", "Gamma", "Delta")]
        entries.append(type_entry(tsx_path, "Props"))
        public = [{"path": ts_path, "symbol": "make"}, {"path": tsx_path, "symbol": "View"}]
        rules, evidence = self.rules(self.manifest(types=entries, public_symbols=public))
        self.assertEqual(set(), rules)
        self.assertEqual("typescript-compiler-api", evidence["mode"])
        self.assertEqual(2, len(evidence["analyzed_files"]))
        self.assertEqual(5, evidence["type_count"])

    def test_uncataloged_type_is_must(self) -> None:
        self.write("interface Missing {}")
        rules, _ = self.rules(self.manifest())
        self.assertIn("TSTYPE001", rules)

    def test_stale_catalog_entry_is_must(self) -> None:
        path = self.write("interface Present {}")
        rules, _ = self.rules(self.manifest(types=[type_entry(path, "Present"), type_entry(path, "Gone")]))
        self.assertIn("TSTYPE002", rules)

    def test_owner_mismatch_is_must(self) -> None:
        path = self.write("interface Owned {}")
        rules, _ = self.rules(self.manifest(types=[type_entry(path, "Owned", owner="other")]))
        self.assertIn("TSTYPE003", rules)

    def test_parse_failure_is_configuration_blocked(self) -> None:
        self.write("interface Broken { value: ")
        diagnostics, evidence = analyze_typescript(self.manifest(), self.root)
        match = [item for item in diagnostics if item["rule_id"] == "TSAST002"]
        self.assertTrue(match)
        self.assertTrue(match[0]["configuration"])
        self.assertEqual([], evidence["analyzed_files"])

    def test_missing_public_symbol_is_must(self) -> None:
        path = self.write("export interface Present {}")
        rules, _ = self.rules(self.manifest(
            types=[type_entry(path, "Present")],
            public_symbols=[{"path": path, "symbol": "Missing"}],
        ))
        self.assertIn("TSSYM001", rules)

    def test_missing_typescript_compiler_is_configuration_blocked(self) -> None:
        path = self.write("interface Present {}")
        (self.root / "frontend" / "node_modules" / "typescript").unlink()
        diagnostics, evidence = analyze_typescript(
            self.manifest(types=[type_entry(path, "Present")]), self.root
        )
        match = [item for item in diagnostics if item["rule_id"] == "TSAST001"]
        self.assertTrue(match)
        self.assertTrue(match[0]["configuration"])
        self.assertEqual("not-run", evidence["mode"])


if __name__ == "__main__":
    unittest.main()
