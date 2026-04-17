# TODO

## Tests rotos pre-existentes

- [ ] `tests/test_integration_edge_cases.py::TestFormOutputEdgeCases::test_display_data_with_field_order` — espera 8 campos pero `Materia` ahora tiene 9 (se agregó `optativa`). Actualizar el assert a `== 9` y agregar `"optativa"` al `field_order`.
- [ ] `tests/test_ui_schema_introspector.py::TestSchemaIntrospector::test_get_fields_returns_all_fields` — mismo problema: `assert len(fields) == 8` debe ser `== 9` y validar que `"optativa" in fields`.
