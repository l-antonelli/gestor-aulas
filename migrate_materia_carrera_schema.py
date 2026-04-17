#!/usr/bin/env python3
"""
Migration script to update materia_carrera link table schema.

Changes:
1. Add anio_carrera and cuatrimestre_carrera to materia_carrera table
2. Remove anio_carrera and cuatrimestre_carrera from materias table
"""

import sys
sys.path.append('.')

import sqlite3
from pathlib import Path

def migrate_database():
    """Update schema for materia_carrera link table."""
    
    db_path = Path("data/database.db")
    
    if not db_path.exists():
        print("❌ Database file not found at data/database.db")
        return False
    
    print(f"📂 Connecting to database: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Step 1: Check current schema of materia_carrera
        print("\n1️⃣ Checking materia_carrera table schema...")
        cursor.execute("PRAGMA table_info(materia_carrera)")
        mc_columns = {row[1]: row for row in cursor.fetchall()}
        
        has_anio = "anio_carrera" in mc_columns
        has_cuatrimestre = "cuatrimestre_carrera" in mc_columns
        
        if has_anio and has_cuatrimestre:
            print("ℹ️ materia_carrera already has anio_carrera and cuatrimestre_carrera columns")
        else:
            print("➕ Need to add columns to materia_carrera")
            
            # Get existing data
            cursor.execute("SELECT materia_codigo, carrera_codigo FROM materia_carrera")
            existing_links = cursor.fetchall()
            print(f"   Found {len(existing_links)} existing links")
            
            # Drop and recreate table with new schema
            print("   Recreating materia_carrera table...")
            cursor.execute("DROP TABLE IF EXISTS materia_carrera")
            cursor.execute("""
                CREATE TABLE materia_carrera (
                    materia_codigo VARCHAR NOT NULL,
                    carrera_codigo VARCHAR NOT NULL,
                    anio_carrera INTEGER NOT NULL DEFAULT 1,
                    cuatrimestre_carrera INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (materia_codigo, carrera_codigo),
                    FOREIGN KEY(materia_codigo) REFERENCES materias (codigo),
                    FOREIGN KEY(carrera_codigo) REFERENCES carreras (codigo),
                    CHECK (anio_carrera >= 1 AND anio_carrera <= 6),
                    CHECK (cuatrimestre_carrera >= 1 AND cuatrimestre_carrera <= 2)
                )
            """)
            
            # Restore existing links with default values
            for materia_codigo, carrera_codigo in existing_links:
                cursor.execute("""
                    INSERT INTO materia_carrera (materia_codigo, carrera_codigo, anio_carrera, cuatrimestre_carrera)
                    VALUES (?, ?, 1, 1)
                """, (materia_codigo, carrera_codigo))
            
            print(f"   ✅ Restored {len(existing_links)} links with default values")
        
        # Step 2: Check materias table
        print("\n2️⃣ Checking materias table schema...")
        cursor.execute("PRAGMA table_info(materias)")
        mat_columns = {row[1]: row for row in cursor.fetchall()}
        
        columns_to_remove = []
        if "anio_carrera" in mat_columns:
            columns_to_remove.append("anio_carrera")
        if "cuatrimestre_carrera" in mat_columns:
            columns_to_remove.append("cuatrimestre_carrera")
        
        if columns_to_remove:
            print(f"   Need to remove columns: {', '.join(columns_to_remove)}")
            
            # SQLite doesn't support DROP COLUMN directly, need to recreate table
            print("   Recreating materias table...")
            
            # Get existing data
            cursor.execute("SELECT codigo, nombre, cupo, horas_semanales, periodo FROM materias")
            existing_materias = cursor.fetchall()
            print(f"   Found {len(existing_materias)} existing materias")
            
            # Drop and recreate
            cursor.execute("DROP TABLE IF EXISTS materias")
            cursor.execute("""
                CREATE TABLE materias (
                    codigo VARCHAR NOT NULL,
                    nombre VARCHAR NOT NULL,
                    cupo INTEGER NOT NULL,
                    horas_semanales INTEGER NOT NULL,
                    periodo VARCHAR NOT NULL DEFAULT 'cuatrimestral',
                    PRIMARY KEY (codigo),
                    CHECK (cupo > 0),
                    CHECK (horas_semanales > 0)
                )
            """)
            
            # Restore data
            for row in existing_materias:
                cursor.execute("""
                    INSERT INTO materias (codigo, nombre, cupo, horas_semanales, periodo)
                    VALUES (?, ?, ?, ?, ?)
                """, row)
            
            print(f"   ✅ Restored {len(existing_materias)} materias")
        else:
            print("   ℹ️ materias table already has correct schema")
        
        conn.commit()
        
        # Verify final schema
        print("\n3️⃣ Verifying final schema...")
        cursor.execute("PRAGMA table_info(materia_carrera)")
        mc_final = [row[1] for row in cursor.fetchall()]
        print(f"   materia_carrera columns: {', '.join(mc_final)}")
        
        cursor.execute("PRAGMA table_info(materias)")
        mat_final = [row[1] for row in cursor.fetchall()]
        print(f"   materias columns: {', '.join(mat_final)}")
        
        conn.close()
        
        print("\n✅ Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)
