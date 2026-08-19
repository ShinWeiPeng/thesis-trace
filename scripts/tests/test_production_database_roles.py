import unittest

from scripts.test_production_database_roles import render_role_bootstrap


class ProductionDatabaseRoleRenderingTests(unittest.TestCase):
    def test_rebinds_every_database_reference_with_identifier_quoting(self) -> None:
        rendered = render_role_bootstrap(
            "ALTER DATABASE thesis_trace OWNER TO migration;\n"
            "GRANT CONNECT ON DATABASE thesis_trace TO api;",
            'ci-database"quoted',
        )

        self.assertNotIn("DATABASE thesis_trace", rendered)
        self.assertEqual(rendered.count('DATABASE "ci-database""quoted"'), 2)

    def test_fails_closed_when_bootstrap_reference_count_changes(self) -> None:
        with self.assertRaisesRegex(ValueError, "database references changed"):
            render_role_bootstrap("ALTER DATABASE thesis_trace OWNER TO migration;", "ci")


if __name__ == "__main__":
    unittest.main()
