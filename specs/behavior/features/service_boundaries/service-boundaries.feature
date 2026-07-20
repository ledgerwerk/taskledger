@area-service_boundaries @feature-service-boundaries @generated
Feature: Service Boundaries

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-service-boundaries
  Rule: Service Boundaries

    @req-REQ-0048 @ac-AC-0526
    Example: Boundary Whitelists Include Reasons
      Given the pytest test setup is prepared
      When boundary whitelists include reasons is executed
      Then key is truthy
      Then reason.strip succeeds

    @req-REQ-0048 @ac-AC-0530
    Example: Service Module Line Budget
      Given the pytest test setup is prepared
      When service module line budget is executed
      Then unexpected is falsy
      Then stale is falsy

    @req-REQ-0048 @ac-AC-0529
    Example: Service Function Line Budget
      Given the pytest test setup is prepared
      When service function line budget is executed
      Then unexpected is falsy
      Then stale is falsy

    @req-REQ-0048 @ac-AC-0528
    Example: Except Exception Sites Are Whitelisted
      Given the pytest test setup is prepared
      When except exception sites are whitelisted is executed
      Then unexpected is falsy
      Then stale is falsy

    @req-REQ-0048 @ac-AC-0527
    Example: Cli Services Imports Are Whitelisted
      Given the pytest test setup is prepared
      When cli services imports are whitelisted is executed
      Then unexpected is falsy
      Then stale is falsy

    @req-REQ-0048 @ac-AC-0532
    Example: Validation Module Has No Private Tasks Imports
      Given the pytest test setup is prepared
      When validation module has no private tasks imports is executed
      Then forbidden is falsy

    @req-REQ-0048 @ac-AC-0531
    Example: Tasks Validation Gate Wrapper Has No Local Import Workaround
      Given the pytest test setup is prepared
      When tasks validation gate wrapper has no local import workaround is executed
      Then target is not None
      Then local_imports is falsy
