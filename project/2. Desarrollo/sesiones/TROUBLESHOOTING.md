# Troubleshooting Guide

## Common Issues and Solutions

### Issue: 'Carrera' object has no attribute 'cantidad_materias'

**Symptoms:**
- Error message: `'Carrera' object has no attribute 'cantidad_materias'`
- Occurs when viewing carrera details or materia completeness panel
- Happens after adding the `cantidad_materias` field

**Root Cause:**
This error can occur due to:
1. **Streamlit module caching**: Streamlit caches imported modules, and old versions without the new field may be cached
2. **Database migration not applied**: The column doesn't exist in the database
3. **Converter not updated**: The domain/DB converters don't include the new field

**Solutions:**

#### Solution 1: Restart Streamlit (Most Common)
```bash
# Stop the current process
# Ctrl+C or kill the process

# Restart
python run.py
```

This clears Streamlit's module cache and reloads all code with the new field definitions.

#### Solution 2: Verify Database Migration
```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()
cursor.execute('PRAGMA table_info(carreras)')
columns = [row[1] for row in cursor.fetchall()]
print('Columns:', columns)
print('cantidad_materias exists:', 'cantidad_materias' in columns)
conn.close()
"
```

If the column doesn't exist, run:
```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()
cursor.execute('ALTER TABLE carreras ADD COLUMN cantidad_materias INTEGER DEFAULT NULL')
conn.commit()
conn.close()
print('✅ Column added')
"
```

#### Solution 3: Verify Converters
Check that `src/database/converters.py` includes `cantidad_materias` in both:
- `to_db()` for Carrera
- `to_domain()` for Carrera

#### Solution 4: Use Safe Attribute Access
The code now uses `getattr(carrera, 'cantidad_materias', None)` as a fallback to handle edge cases.

### Issue: Carreras show "Sin cantidad definida" warning

**Symptoms:**
- All or some carreras show ⚠️ "Cantidad de materias no definida"
- This is expected behavior, not an error

**Explanation:**
This is the intended behavior when `cantidad_materias` is `NULL` in the database. It means the expected number of materias hasn't been configured yet.

**Solution:**
1. Go to "🎓 Carreras" page
2. Edit the carrera
3. Set the "Cantidad de Materias" field
4. Save

### Issue: Materia page shows incorrect completeness percentage

**Symptoms:**
- Percentage shows > 100%
- Materias assigned exceeds expected count

**Explanation:**
This can happen if:
1. The `cantidad_materias` was set too low
2. Materias were added after setting the count
3. The count includes materias from multiple plans

**Solution:**
1. Review the actual number of materias in the curriculum
2. Update `cantidad_materias` to the correct value
3. The system allows > 100% to handle this case gracefully

### Issue: Changes to cantidad_materias don't appear immediately

**Symptoms:**
- Updated `cantidad_materias` in form
- Status still shows old value

**Root Cause:**
- Browser cache or Streamlit state not refreshed

**Solution:**
1. Click the "Rerun" button in Streamlit (top-right)
2. Or refresh the browser page (F5)
3. Or use the "Clear cache" option in Streamlit menu

### Issue: Database locked error

**Symptoms:**
- Error: `database is locked`
- Occurs when multiple processes access the database

**Solution:**
1. Close any other connections to the database
2. Stop any running Streamlit instances
3. Restart the application

### Issue: Validation shows wrong materia count

**Symptoms:**
- Count of assigned materias doesn't match reality
- Materias appear in list but not in count

**Root Cause:**
- Link table (`materia_carrera`) might have stale data
- Materias might be soft-deleted but links remain

**Solution:**
```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()

# Check link table
cursor.execute('SELECT COUNT(*) FROM materia_carrera WHERE carrera_codigo = \"ING001\"')
print('Links:', cursor.fetchone()[0])

# Check actual materias
cursor.execute('''
    SELECT m.codigo, m.nombre 
    FROM materias m
    JOIN materia_carrera mc ON m.codigo = mc.materia_codigo
    WHERE mc.carrera_codigo = \"ING001\"
''')
for row in cursor.fetchall():
    print(f'  - {row[0]}: {row[1]}')

conn.close()
"
```

## Debugging Tips

### Enable Debug Mode

Add to your page:
```python
import streamlit as st

# Show debug info
if st.checkbox("Show Debug Info"):
    st.write("Session State:", st.session_state)
    st.write("Carrera:", carrera)
    st.write("Has cantidad_materias:", hasattr(carrera, 'cantidad_materias'))
```

### Check Object Attributes

```python
# In your code
print(f"Carrera attributes: {dir(carrera)}")
print(f"Carrera dict: {carrera.__dict__ if hasattr(carrera, '__dict__') else 'N/A'}")
```

### Verify Database State

```bash
# Check database directly
sqlite3 data/database.db "SELECT * FROM carreras;"
sqlite3 data/database.db "SELECT * FROM materia_carrera;"
```

### Test Validation Functions

```python
from src.services.carrera_validation import get_carrera_status

with next(get_session()) as session:
    try:
        status = get_carrera_status(session, "ING001")
        print(f"Status: {status.get_mensaje_estado()}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
```

## Prevention

### Best Practices

1. **Always restart Streamlit after model changes**
   - Domain model changes
   - Database model changes
   - Converter changes

2. **Test changes in isolation first**
   - Use Python scripts to test before UI
   - Verify database state before and after

3. **Use migrations for schema changes**
   - Document all ALTER TABLE commands
   - Keep migration scripts for reference

4. **Handle optional fields gracefully**
   - Use `Optional[T]` in Pydantic models
   - Use `getattr()` for safe attribute access
   - Provide sensible defaults

5. **Clear cache when in doubt**
   - Streamlit menu → "Clear cache"
   - Or restart the application

## Getting Help

If you encounter an issue not covered here:

1. Check the error message carefully
2. Look for the file and line number
3. Verify the database state
4. Check if a restart fixes it
5. Review recent code changes
6. Test with a minimal example

## Related Documentation

- `CARRERA_COMPLETENESS_FEATURE.md`: Feature documentation
- `CARRERA_MATERIA_IMPLEMENTATION.md`: Implementation details
- `project/modelo-er.md`: Data model documentation
