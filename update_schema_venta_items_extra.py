from app import create_app
from app.db import get_db
import psycopg2
import sys

def update_db_schema():
    app = create_app()
    with app.app_context():
        print("Connecting to database via Flask app context...")
        db = get_db()
        if not db:
            print("Failed to get database connection.")
            sys.exit(1)

        try:
            # Note: The db object from get_db() might not be in autocommit mode by default usually,
            # but let's try setting it or just commiting.
            # get_db returns a psycopg2 connection.
            
            cursor = db.cursor()
            
            print("Updating table venta_items...")
            
            # Add es_extra column
            try:
                cursor.execute("ALTER TABLE venta_items ADD COLUMN es_extra BOOLEAN DEFAULT FALSE")
                print("- Column es_extra added to venta_items.")
                db.commit() # Commit changes
            except psycopg2.errors.DuplicateColumn:
                db.rollback()
                print("- Column es_extra already exists in venta_items.")
            except Exception as e:
                db.rollback()
                raise e
            
            print("Migration completed successfully.")
            cursor.close()
            
        except Exception as e:
            print("Critical Error during migration.")
            print(repr(e))
            sys.exit(1)

if __name__ == "__main__":
    update_db_schema()
