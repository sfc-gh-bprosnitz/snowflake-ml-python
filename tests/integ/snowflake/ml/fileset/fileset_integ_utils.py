#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#
import os
import tempfile
from typing import Union

from snowflake import snowpark

# The list below defines the schema of the resultset generated by _get_result_query().
# Each list element is a 2-tuple consists of a column name and the corresponding column data type,
_TEST_RESULTSET_SCHEMA = [
    ("NUMBER_INT_COL", "NUMBER(38,0)"),
    ("NUMBER_FIXED_POINT_COL", "NUMBER(15,1)"),
    ("TINYINT_COL", "TINYINT"),
    ("SMALLINT_COL", "SMALLINT"),
    ("INT_COL", "INT"),
    ("BIGINT_COL", "BIGINT"),
    ("FLOAT_COL", "FLOAT"),
    ("DOUBLE_COL", "DOUBLE"),
]


def upload_file_to_snowflake(
    sp_session: snowpark.Session, file_path: str, snowflake_stage: str, stage_relative_path: str
) -> None:
    """Upload a file from local to a Snowflake stage."""
    query = f"put file://{file_path} @{snowflake_stage}/{stage_relative_path} auto_compress=false"
    sp_session.sql(query).collect()


def upload_files_to_snowflake(sp_session: snowpark.Session, snowflake_stage: str, content: bytes) -> None:
    """Upload multiple files to a Snowflake stage.

    All the files will have the same content. The uploaded files will have the following structure:
    - Stage
        - train
            - dataset
                - helloworld1.txt
                - helloworld2.txt
            - helloworld.txt
        - test
            - testhelloworld.txt

    Args:
        sp_session: An active spark session.
        snowflake_stage: The destination of uploaded stage file.
        content: The content of uploaded stage file.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        for directory, filename in [
            ("train/dataset/", "helloworld1.txt"),
            ("train/dataset/", "helloworld2.txt"),
            ("train/", "helloworld.txt"),
            ("test/", "testhelloworld.txt"),
        ]:
            local_path = os.path.join(temp_dir, filename)
            with open(local_path, "wb") as f:
                f.write(content)
            upload_file_to_snowflake(sp_session, local_path, snowflake_stage, directory)


def delete_files_from_snowflake_stage(sp_session: snowpark.Session, snowflake_stage: str) -> None:
    """Delete all the files in a snowflake stage."""
    query = f"remove @{snowflake_stage}/"
    sp_session.sql(query).collect()


def create_tmp_snowflake_stage_if_not_exists(
    sp_session: snowpark.Session, snowflake_stage: str, sse: bool = True
) -> None:
    """Create a snowflake stage with server side encryption."""
    query = f"create temp stage {snowflake_stage}"
    if sse:
        query += " ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')"
    sp_session.sql(query).collect()


def get_fileset_query(row_number: int) -> str:
    """Return a SQL query which could generate an arbitary resultset with the given number of rows."""
    root_col = "row_num"
    inner_table = (
        f"select (row_number() over (order by 1) + 0.11) as {root_col} "
        f"from table(generator(rowcount => {row_number}))"
    )
    cast_queries = []
    for col, col_type in _TEST_RESULTSET_SCHEMA:
        cast_query = f"cast({root_col} as {col_type}) as {col}"
        cast_queries.append(cast_query)
    final_query = f"select {', '.join(cast_queries)} from ({inner_table})"
    return final_query


def get_column_min(col_name: str) -> Union[int, float]:
    """Return the expected minimum value of the given column in the arbitary resultset."""
    if col_name == "NUMBER_FIXED_POINT_COL":
        return 1.1
    if col_name in ["FLOAT_COL", "DOUBLE_COL"]:
        return 1.11
    return 1


def get_column_max(col_name: str, row_number: int) -> Union[int, float]:
    """Return the expected maximum value of the given column in the arbitary resultset."""
    if col_name == "NUMBER_FIXED_POINT_COL":
        return 0.1 + row_number
    if col_name in ["FLOAT_COL", "DOUBLE_COL"]:
        return 0.11 + row_number
    return row_number


def get_column_avg(col_name: str, row_number: int) -> Union[int, float]:
    """Return the expected average value of the given column in the arbitary resultset."""
    if col_name == "NUMBER_FIXED_POINT_COL":
        return (1.2 + row_number) / 2
    if col_name in ["FLOAT_COL", "DOUBLE_COL"]:
        return (1.22 + row_number) / 2
    return (1 + row_number) / 2