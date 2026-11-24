# CTI Component Manager — PyMySQL dict parameter fix

Date: 2026-08-11

## Root cause

`ServiceRegistry.ensure_default_services()` passed the complete in-memory component
record to PyMySQL. The record included a native Python `config` dictionary even
though SQL only referenced `config_json`. PyMySQL eagerly escapes every value in a
named-parameter mapping, including unused keys, and therefore raised:

`TypeError: dict can not be used as parameter`

The same integration risk existed in other CTI persistence code that builds SQL
parameter mappings from structured dictionaries.

## Changes

1. `cti_services/service_registry.py`
   - Added `_registry_insert_params()`.
   - Native `config` is removed from SQL parameters.
   - `config` is explicitly serialized into `config_json`.
   - Existing runtime values remain preserved on duplicate-key update.

2. `cti_services/db_adapter.py`
   - Added `normalize_sql_params()` as defense in depth.
   - Any native dict reaching the PyMySQL boundary is serialized to JSON.
   - Tuple/list parameters are not modified, preserving normal PyMySQL `IN (...)`
     usage.
   - Applied normalization to `fetch_all`, `fetch_one`, `execute`,
     `execute_many`, and `execute_transaction`.

3. `tests/test_cti_harmonized_architecture.py`
   - Added regression test proving ServiceRegistry never binds native `config`.
   - Added regression test proving DbAdapter serializes dict parameters while
     preserving tuples.

## Validation

`python -m compileall` succeeded.

`python -m unittest discover -s tests -v` result: **6 tests passed**.

A live MariaDB integration test was not run in this environment. No database schema
change is required for this error; `cti_component_registry.config_json` remains the
correct persistence column.
