# Office Importers Examples

This directory (`examples/ingest/office/importers`) contains examples and regression test artifacts for "office" related document importers in Beancount. It serves as a reference for structuring ingestion logic and testing.

## Overview

The `importers` directory is designed to hold subdirectories for individual importers. Currently, it includes the `acme` example, which demonstrates the artifacts required for regression testing a PDF importer.

## Concepts

### Regression Testing Artifacts
The primary focus of this directory is regression testing. Instead of storing the full importer code here, it stores the *expected outputs* of the ingestion process. This allows developers to verify that the extraction and identification logic remains stable over time.

Key artifacts include:
*   **`.extract` Files:** These files contain the expected Beancount directives returned by the importer and rendered as text. The version 2 ingestion regression harness compares the rendered accounting entries with this file; it does not compare raw PDF text.
*   **`.file_account` Files:** These files contain the Beancount account string (e.g., `Assets:Bank:Checking`) that the importer should identify for a given document. This ensures the account matching logic works as expected.

## Directory Structure

*   **`acme/`**: Contains artifacts for a hypothetical "Acme Bank" importer.
    *   `acmebank1.pdf.extract`: The expected rendered Beancount directives for `acmebank1.pdf`.
    *   `acmebank1.pdf.file_account`: The expected account for `acmebank1.pdf`.
    *   `docs.md`: Documentation specific to the Acme importer.

## Intention

This structure illustrates a pattern for maintaining robust importers:
1.  **Separation of Concerns:** The test data is separated from the importer code (which would typically reside in a Python module).
2.  **Snapshot Testing:** The `.extract` and `.file_account` files act as snapshots. Any deviation in the output of the importer during a test run would signal a regression.
