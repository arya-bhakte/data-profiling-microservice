from typing import Dict, List


def profile_table_schema(conn, table_name: str) -> Dict:
    if "." in table_name:
        schema_name, table_only = table_name.split(".", 1)
    else:
        schema_name, table_only = "public", table_name
        
    query = """
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default,
            character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = %s
        AND table_name = %s
        ORDER BY ordinal_position;
    """
    
    with conn.cursor() as cursor:
        cursor.execute(query, (schema_name, table_only))
        rows = cursor.fetchall()
        
    if not rows:
        raise ValueError(f"Table {table_name} not found or has no columns.")
    
    columns: List[Dict] = []
    for column_name, data_type, is_nullable, default_val, max_length in rows:
        column_info = {
            "name": column_name,
            "db_type": data_type,
            "nullable": is_nullable == "YES",
        }
        
        if default_val is not None:
            column_info["default"] = default_val
        if max_length:
            column_info["max_length"] = max_length
            
        columns.append(column_info)
    
    count_query = f'SELECT COUNT(*) FROM {schema_name}.{table_only};'

    with conn.cursor() as cursor:
        cursor.execute(count_query)
        row_count = cursor.fetchone()[0]
    
    return {
        "table_name": table_name,
        "schema": schema_name,
        "columns": columns,
        "column_count": len(columns),
        "approx_row_count": row_count,  
        "sampled_rows": row_count,       
        "row_count": row_count,          
    }