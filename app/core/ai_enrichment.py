import os
import json
import logging
from typing import Dict, Any, List
from openai import OpenAI

logger = logging.getLogger(__name__)


class AIEnrichmentError(Exception):
    pass


def generate_semantic_summary(profile_result: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if not profile_result:
            raise AIEnrichmentError("Profile result is empty")

        if "table_name" not in profile_result:
            raise AIEnrichmentError("Profile result missing 'table_name'")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise AIEnrichmentError("OPENAI_API_KEY not set")

        client = OpenAI(api_key=api_key)

        prompt = _build_prompt(profile_result)

        logger.info(
            f"Calling OpenAI for table '{profile_result.get('table_name')}'"
        )

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            max_tokens=800,  # Increased for column_roles
            temperature=0.2,  # Lower for more consistent JSON
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a database profiling expert. "
                        "Analyze table schemas and classify columns semantically. "
                        "CRITICAL: Always return VALID JSON with ALL required fields. "
                        "Never skip the column_roles field."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        response_text = response.choices[0].message.content
        if not response_text:
            raise AIEnrichmentError("Empty response from OpenAI")

        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        # Log raw response for debugging
        logger.debug(f"Raw OpenAI response: {response_text[:300]}...")

        try:
            summary = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response: {response_text}")
            raise AIEnrichmentError(f"Invalid JSON from OpenAI: {e}")

        # Log what keys we got
        logger.info(f"OpenAI returned keys: {list(summary.keys())}")

        required_keys = [
            "table_description",
            "recommended_dimensions",
            "recommended_measures",
            "data_quality_notes"
        ]

        # Check required keys
        for key in required_keys:
            if key not in summary:
                raise AIEnrichmentError(f"Missing required key: {key}")

        # Validate types
        if not isinstance(summary["recommended_dimensions"], list):
            raise AIEnrichmentError("recommended_dimensions must be a list")
        if not isinstance(summary["recommended_measures"], list):
            raise AIEnrichmentError("recommended_measures must be a list")
        if not isinstance(summary["data_quality_notes"], list):
            raise AIEnrichmentError("data_quality_notes must be a list")

        # Handle column_roles
        if "column_roles" not in summary:
            logger.warning("column_roles missing from OpenAI response, generating fallback")
            summary["column_roles"] = _generate_fallback_roles(profile_result)
        elif not isinstance(summary["column_roles"], dict):
            logger.warning("column_roles is not a dict, generating fallback")
            summary["column_roles"] = _generate_fallback_roles(profile_result)

        logger.info(f"AI enrichment successful for table '{profile_result.get('table_name')}'")
        return summary

    except AIEnrichmentError:
        raise
    except Exception as e:
        raise AIEnrichmentError(
            f"AI enrichment failed: {type(e).__name__}: {str(e)}"
        ) from e


def _generate_fallback_roles(profile_result: Dict[str, Any]) -> Dict[str, str]:
    columns = profile_result.get("columns", [])
    statistics = profile_result.get("statistics", {})
    roles = {}

    for col in columns:
        if not isinstance(col, dict):
            continue

        col_name = col.get("name", "")
        col_type = col.get("db_type", "").lower()
        nullable = col.get("nullable", True)

        # Heuristic classification
        if not nullable and "id" in col_name.lower():
            roles[col_name] = "identifier"
        elif "timestamp" in col_type or "date" in col_type or "time" in col_type:
            roles[col_name] = "timestamp"
        elif "int" in col_type or "float" in col_type or "numeric" in col_type or "decimal" in col_type:
            # Check if it looks like a measure (high distinct count relative to rows)
            stats = statistics.get(col_name, {})
            distinct = stats.get("distinct_count", 0)
            if distinct > 10:  # Arbitrary threshold
                roles[col_name] = "measure"
            else:
                roles[col_name] = "dimension"
        else:
            # Categorical/text fields
            roles[col_name] = "dimension"

    logger.info(f"Generated fallback roles for {len(roles)} columns")
    return roles


def _build_prompt(profile_result: Dict[str, Any]) -> str:
    table_name = profile_result.get("table_name", "unknown")
    schema = profile_result.get("schema", "public")
    row_count = profile_result.get("row_count", 0)
    column_count = profile_result.get("column_count", 0)
    columns = profile_result.get("columns", [])
    statistics = profile_result.get("statistics", {})

    column_lines = []

    if isinstance(columns, list):
        for col in columns:
            if not isinstance(col, dict):
                continue

            col_name = col.get("name", "unknown")
            col_type = col.get("db_type", "unknown")
            nullable = col.get("nullable", True)
            default = col.get("default")

            parts = [f"• {col_name} ({col_type})"]
            
            if not nullable:
                parts.append("NOT NULL")
            if default:
                parts.append(f"DEFAULT: {default}")
            
            # Add statistics
            if col_name in statistics:
                stats = statistics[col_name]
                if isinstance(stats, dict):
                    stat_parts = []
                    if "null_percent" in stats:
                        stat_parts.append(f"nulls={stats['null_percent']:.1f}%")
                    if "distinct_count" in stats:
                        stat_parts.append(f"distinct={stats['distinct_count']}")
                    if "min" in stats and "max" in stats:
                        stat_parts.append(f"range=[{stats['min']}..{stats['max']}]")
                    if "mean" in stats:
                        stat_parts.append(f"avg={stats['mean']:.2f}")
                    
                    if stat_parts:
                        parts.append(f"[{', '.join(stat_parts)}]")

            column_lines.append(" ".join(parts))

    if not column_lines:
        column_lines.append("• No column metadata available")

    # Get all column names for the example
    column_names = [col.get("name") for col in columns if isinstance(col, dict) and col.get("name")]

    prompt = f"""
Analyze this database table and classify each column.

TABLE: {schema}.{table_name}
ROWS: {row_count:,}
COLUMNS: {column_count}

COLUMN DETAILS:
{chr(10).join(column_lines)}

Return a JSON object with this EXACT structure:

{{
  "table_description": "Brief business description (1-2 sentences)",
  "recommended_dimensions": ["col1", "col2"],
  "recommended_measures": ["col3"],
  "data_quality_notes": [
    "Note about data quality",
    "Note about patterns",
    "Recommendation"
  ],
  "column_roles": {{
    "col1": "identifier",
    "col2": "dimension",
    "col3": "measure",
    "col4": "timestamp"
  }}
}}

COLUMN ROLE DEFINITIONS:
- identifier: Primary/foreign keys, unique IDs (high cardinality, often NOT NULL)
- dimension: Categorical fields for grouping (status, category, name, email)
- measure: Numeric fields for aggregation (amount, quantity, age, count)
- timestamp: Date/time fields for temporal analysis

IMPORTANT RULES:
1. recommended_dimensions = list of column names ONLY (just strings)
2. recommended_measures = list of column names ONLY (just strings)
3. column_roles = MUST include ALL columns: {column_names}
4. Use the statistics provided to make informed classifications

EXAMPLE for a user table:
{{
  "table_description": "User account information table with 8 records.",
  "recommended_dimensions": ["name", "email"],
  "recommended_measures": ["age"],
  "data_quality_notes": [
    "All columns have complete data (0% nulls)",
    "The id column serves as a unique identifier",
    "The created_at field shows no variation (single timestamp)"
  ],
  "column_roles": {{
    "id": "identifier",
    "name": "dimension",
    "email": "dimension",
    "age": "measure",
    "created_at": "timestamp"
  }}
}}

Return ONLY the JSON. No explanations. No markdown.
""".strip()

    return prompt


def enrich_profile_with_ai(
    profile_result: Dict[str, Any],
    fail_silently: bool = True
) -> Dict[str, Any]:
    try:
        summary = generate_semantic_summary(profile_result)

        enriched = profile_result.copy()
        
        # Add role to each column 
        if "columns" in enriched and isinstance(enriched["columns"], list):
            column_roles = summary.get("column_roles", {})
            for col in enriched["columns"]:
                col_name = col.get("name")
                if col_name and col_name in column_roles:
                    col["role"] = column_roles[col_name]
                    logger.debug(f"Assigned role '{column_roles[col_name]}' to column '{col_name}'")
                else:
                    col["role"] = "unknown"
                    logger.warning(f"No role found for column '{col_name}', assigned 'unknown'")
        
        # Add ai_summary 
        enriched["ai_summary"] = {
            "table_description": summary["table_description"],
            "recommended_dimensions": summary["recommended_dimensions"],
            "recommended_measures": summary["recommended_measures"],
            "data_quality_notes": summary["data_quality_notes"]
        }

        logger.info(f"Successfully enriched profile with AI metadata and column roles")
        return enriched

    except AIEnrichmentError as e:
        logger.error(f"AI enrichment failed: {e}")
        if fail_silently:
            logger.info("Returning profile without AI enrichment")
            return profile_result
        raise
    except Exception as e:
        logger.error(f"Unexpected error in AI enrichment: {e}", exc_info=True)
        if fail_silently:
            return profile_result
        raise