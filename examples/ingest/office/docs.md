# Office Ingest Examples

This directory serves as a reference for structuring regression test artifacts within the Beancount ingestion framework. It demonstrates how to organize expected output data to verify the correctness of document importers.

## Purpose

The main goal is to separate test data from implementation code. By storing "golden" files—which represent the correct, expected output of various ingestion stages—developers can ensure that changes to the importer logic do not cause regressions in text extraction or account identification.

## Directory Structure

*   **`importers/`**: A container for importer-specific test data.
    *   **`acme/`**: An example subdirectory for a hypothetical "Acme Bank" importer.

## Key Concepts & Artifacts

The example uses specific file extensions to represent different stages of the ingestion testing process:

*   **`.extract` Files** (e.g., `acmebank1.pdf.extract`)
    *   **Content:** The expected Beancount directives returned by the importer and rendered as text.
    *   **Usage:** The version 2 ingestion regression harness compares the rendered accounting entries with this file. Raw PDF text is a separate intermediate result.

*   **`.file_account` Files** (e.g., `acmebank1.pdf.file_account`)
    *   **Content:** The target Beancount account name (e.g., `Assets:US:AcmeBank`).
    *   **Usage:** Used to verify the "filing" logic. It ensures that the importer correctly identifies which account a given document belongs to based on its filename or content.
