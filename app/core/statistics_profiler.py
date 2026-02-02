import logging
from typing import Any, Dict, List
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)


def profile_column_statistics(
    conn: Connection,
    table_name: str,
    columns: List[Dict[str, Any]],
    top_n: int = 10,
    percentiles: List[float] = None
) -> Dict[str, Dict[str, Any]]:
    if percentiles is None:
        percentiles = [25, 50, 75, 90, 95, 99]
    
    cursor = conn.cursor()
    statistics = {}
    
    try:
        # Get total row count 
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        total_rows = cursor.fetchone()[0]
        
        if total_rows == 0:
            logger.warning(f"Table {table_name} has 0 rows")
            return {}
        
        for col in columns:
            col_name = col["name"]
            col_type = col["db_type"].lower()
            
            logger.info(f"Profiling column: {col_name} ({col_type})")
            
            stats = _profile_single_column(
                cursor=cursor,
                table_name=table_name,
                col_name=col_name,
                col_type=col_type,
                total_rows=total_rows,
                top_n=top_n,
                percentiles=percentiles
            )
            
            statistics[col_name] = stats
        
        return statistics
        
    except Exception as e:
        logger.error(f"Failed to profile statistics: {e}", exc_info=True)
        raise
    finally:
        cursor.close()


def _profile_single_column(
    cursor,
    table_name: str,
    col_name: str,
    col_type: str,
    total_rows: int,
    top_n: int,
    percentiles: List[float]
) -> Dict[str, Any]:
    
    stats = {}
    
    # Null analysis
    cursor.execute(
        f"""
        SELECT 
            COUNT(*) FILTER (WHERE "{col_name}" IS NULL) as null_count,
            COUNT(DISTINCT "{col_name}") as distinct_count
        FROM {table_name}
        """
    )
    row = cursor.fetchone()
    null_count = row[0]
    distinct_count = row[1]
    
    stats["null_count"] = null_count
    stats["null_percent"] = round((null_count / total_rows) * 100, 2) if total_rows > 0 else 0
    stats["distinct_count"] = distinct_count
    stats["distinct_percent"] = round((distinct_count / total_rows) * 100, 2) if total_rows > 0 else 0
    
    if _is_numeric_type(col_type):
        # Numeric statistics
        numeric_stats = _profile_numeric_column(
            cursor, table_name, col_name, percentiles
        )
        stats.update(numeric_stats)
        
    elif _is_text_type(col_type):
        # Categorical statistics
        categorical_stats = _profile_categorical_column(
            cursor, table_name, col_name, total_rows, top_n
        )
        stats.update(categorical_stats)
    
    elif _is_temporal_type(col_type):
        # Temporal statistics
        temporal_stats = _profile_temporal_column(
            cursor, table_name, col_name
        )
        stats.update(temporal_stats)
    
    return stats


def _profile_numeric_column(
    cursor,
    table_name: str,
    col_name: str,
    percentiles: List[float]
) -> Dict[str, Any]:
    
    stats = {}
    
    cursor.execute(
        f"""
        SELECT 
            MIN("{col_name}") as min_val,
            MAX("{col_name}") as max_val,
            AVG("{col_name}") as mean_val,
            STDDEV("{col_name}") as stddev_val
        FROM {table_name}
        WHERE "{col_name}" IS NOT NULL
        """
    )
    row = cursor.fetchone()
    
    if row and row[0] is not None:
        stats["min"] = float(row[0]) if row[0] is not None else None
        stats["max"] = float(row[1]) if row[1] is not None else None
        stats["mean"] = round(float(row[2]), 4) if row[2] is not None else None
        stats["stddev"] = round(float(row[3]), 4) if row[3] is not None else None
    
    if percentiles:
        percentile_values = _calculate_percentiles(
            cursor, table_name, col_name, percentiles
        )
        stats["percentiles"] = percentile_values
    
    return stats


def _calculate_percentiles(
    cursor,
    table_name: str,
    col_name: str,
    percentiles: List[float]
) -> Dict[str, float]:
    percentile_values = {}
    
    percentile_exprs = []
    for p in percentiles:
        fraction = p / 100.0
        percentile_exprs.append(
            f"PERCENTILE_CONT({fraction}) WITHIN GROUP (ORDER BY \"{col_name}\") as p{int(p)}"
        )
    
    query = f"""
        SELECT {', '.join(percentile_exprs)}
        FROM {table_name}
        WHERE "{col_name}" IS NOT NULL
    """
    
    cursor.execute(query)
    row = cursor.fetchone()
    
    if row:
        for i, p in enumerate(percentiles):
            if row[i] is not None:
                percentile_values[f"p{int(p)}"] = round(float(row[i]), 4)
    
    return percentile_values


def _profile_categorical_column(
    cursor,
    table_name: str,
    col_name: str,
    total_rows: int,
    top_n: int
) -> Dict[str, Any]:
    
    stats = {}
    
    # Top N most common values
    cursor.execute(
        f"""
        SELECT 
            "{col_name}" as value,
            COUNT(*) as count
        FROM {table_name}
        WHERE "{col_name}" IS NOT NULL
        GROUP BY "{col_name}"
        ORDER BY count DESC
        LIMIT {top_n}
        """
    )
    
    top_values = []
    for row in cursor.fetchall():
        value = row[0]
        count = row[1]
        percent = round((count / total_rows) * 100, 2) if total_rows > 0 else 0
        
        top_values.append({
            "value": str(value),
            "count": count,
            "percent": percent
        })
    
    stats["top_values"] = top_values
    
    # String length statistics
    cursor.execute(
        f"""
        SELECT 
            MAX(LENGTH("{col_name}")) as max_len,
            MIN(LENGTH("{col_name}")) as min_len,
            AVG(LENGTH("{col_name}")) as avg_len
        FROM {table_name}
        WHERE "{col_name}" IS NOT NULL
        """
    )
    row = cursor.fetchone()
    
    if row and row[0] is not None:
        stats["max_length"] = row[0]
        stats["min_length"] = row[1]
        stats["avg_length"] = round(float(row[2]), 2) if row[2] is not None else None
    
    return stats


def _profile_temporal_column(
    cursor,
    table_name: str,
    col_name: str
) -> Dict[str, Any]:
    
    stats = {}
    
    cursor.execute(
        f"""
        SELECT 
            MIN("{col_name}") as min_val,
            MAX("{col_name}") as max_val
        FROM {table_name}
        WHERE "{col_name}" IS NOT NULL
        """
    )
    row = cursor.fetchone()
    
    if row and row[0] is not None:
        stats["min"] = str(row[0])
        stats["max"] = str(row[1])
    
    return stats


def _is_numeric_type(col_type: str) -> bool:
    # Check if column type is numeric
    numeric_types = [
        'integer', 'int', 'smallint', 'bigint',
        'decimal', 'numeric', 'real', 'double precision',
        'float', 'serial', 'bigserial', 'money'
    ]
    return any(t in col_type for t in numeric_types)


def _is_text_type(col_type: str) -> bool:
    # Check if column type is text/categorical
    text_types = ['character varying', 'varchar', 'char', 'text', 'character']
    return any(t in col_type for t in text_types)


def _is_temporal_type(col_type: str) -> bool:
    # Check if column type is temporal
    temporal_types = ['timestamp', 'date', 'time']
    return any(t in col_type for t in temporal_types)