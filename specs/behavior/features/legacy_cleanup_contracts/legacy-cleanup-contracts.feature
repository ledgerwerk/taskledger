@area-legacy_cleanup_contracts @feature-legacy-cleanup-contracts @generated
Feature: Legacy Cleanup Contracts

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-legacy-cleanup-contracts
  Rule: Legacy Cleanup Contracts

    @req-REQ-0028 @ac-AC-0334
    Example: Package Initializers Do Not Use Star Imports
      Given the pytest test setup is prepared
      When package initializers do not use star imports is executed
      Then 'import *' is not in text

    @req-REQ-0028 @ac-AC-0335
    Example: V2 Storage Does Not Import Storage Facade
      Given the pytest test setup is prepared
      When v2 storage does not import storage facade is executed
      Then 'from taskledger.storage import' is not in text

    @req-REQ-0028 @ac-AC-0333
    Example: Domain Models Does Not Import Legacy Models Package
      Given the pytest test setup is prepared
      When domain models does not import legacy models package is executed
      Then 'from taskledger.models import' is not in text
