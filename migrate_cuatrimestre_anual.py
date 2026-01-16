"""
Migration script to update cuatrimestre_carrera for annual materias.

Changes:
1. Allow cuatrimestre_carrera = 0 (for annual materias)
2. Update existing annual materias to use 0 instead of 1
"""

import sqlite3
from pathlib import Path

def migrate():
    db_path = Path("data/database.db")
    
    if not db_path.exists():
        print("❌ Database not found")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=" * 70)
    print("MIGRATION: Update cuatrimestre_carrera for annual materias")
    print("=" * 70)
    
    try:
        # Step 1: Check current constraint
        print("\n[1] Checking current schema...")
        cursor.execute("PRAGMA table_info(materia_carrera)")
        columns = cursor.fetchall()
        print(f"    ✓ materia_carrera table has {len(columns)} columns")
        
        # Step 2: Get annual materias
        print("\n[2] Finding annual materias...")
        cursor.execute("""
            SELECT m.codigo, m.nombre, m.periodo
            FROM materias m
            WHERE m.periodo = 'anual'
        """)
        annual_materias = cursor.fetchall()
        print(f"    ✓ Found {len(annual_materias)} annual materias")
        
        # Step 3: Update cuatrimestre_carrera to 0 for annual materias
        print("\n[3] Updating cuatrimestre_carrera for annual materias...")
        updated_count = 0
        
        for materia_codigo, materia_nombre, periodo in annual_materias:
            cursor.execute("""
                UPDATE materia_carrera
                SET cuatrimestre_carrera = 0
                WHERE materia_codigo = ?
                AND cuatrimestre_carrera != 0
            """, (materia_codigo,))
            
            if cursor.rowcount > 0:
                updated_count += cursor.rowcount
                print(f"    ✓ Updated {cursor.rowcount} association(s) for {materia_codigo} - {materia_nombre}")
        
        print(f"\n    Total: {updated_count} associations updated")
        
        # Step 4: Verify changes
        print("\n[4] Verifying changes...")
        cursor.execute("""
            SELECT mc.materia_codigo, m.nombre, mc.carrera_codigo, mc.cuatrimestre_carrera
            FROM materia_carrera mc
            JOIN materias m ON mc.materia_codigo = m.codigo
            WHERE m.periodo = 'anual'
        """)
        results = cursor.fetchall()
        
        all_zero = all(row[3] == 0 for row in results)
        if all_zero:
            print(f"    ✓ All {len(results)} annual materia associations have cuatrimestre_carrera = 0")
        else:
            print(f"    ⚠ Some annual materias still have non-zero cuatrimestre_carrera")
            for row in results:
                if row[3] != 0:
                    print(f"      - {row[0]} ({row[1]}) in {row[2]}: cuatrimestre = {row[3]}")
        
        # Commit changes
        conn.commit()
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        conn.close()
    
    print("=" * 70)

if __name__ == "__main__":
    migrate()
