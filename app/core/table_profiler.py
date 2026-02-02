from typing import Any, Dict
from app.core.schema_profiler import profile_table_schema
from app.core.statistics_profiler import profile_column_statistics


def profile_table(conn, table_name: str) -> Dict[str, Any]:
    schema_profile = profile_table_schema(conn, table_name)

    columns = schema_profile["columns"]
    statistics = profile_column_statistics(
        conn=conn,
        table_name=table_name,
        columns=columns,
        top_n=10, 
        percentiles=[25, 50, 75, 90, 95, 99]  
    )
    
    profile = {
        **schema_profile,
        "statistics": statistics
    }
    
    return profile