from django.db import migrations


def add_missing_student_record_columns(apps, schema_editor):
    StudentRecord = apps.get_model("documents", "StudentRecord")
    table_name = StudentRecord._meta.db_table

    existing_tables = schema_editor.connection.introspection.table_names(
        schema_editor.connection.cursor(),
    )
    if table_name not in existing_tables:
        return

    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(),
            table_name,
        )
    }

    for field_name in ("raw_text", "extraction_source", "extraction_error"):
        if field_name not in existing_columns:
            schema_editor.add_field(StudentRecord, StudentRecord._meta.get_field(field_name))


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0021_studentrecord"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_missing_student_record_columns,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[],
        ),
    ]
