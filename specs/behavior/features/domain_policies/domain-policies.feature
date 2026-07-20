@area-domain_policies @feature-domain-policies @generated
Feature: Domain Policies

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-domain-policies
  Rule: Domain Policies

    @req-REQ-0018 @ac-AC-0207
    Example: Build Policy Context No Lock No Run
      Given the pytest test setup is prepared
      When build policy context no lock no run is executed
      Then ctx.active_stage is None
      Then ctx.lock is None
      Then ctx.run is None

    @req-REQ-0018 @ac-AC-0208
    Example: Build Policy Context With Lock And Run
      Given the pytest test setup is prepared
      When build policy context with lock and run is executed
      Then ctx.active_stage equals 'planning'

    @req-REQ-0018 @ac-AC-0206
    Example: Build Policy Context Lock Without Run
      Given the pytest test setup is prepared
      When build policy context lock without run is executed
      Then ctx.active_stage equals 'implementation'

    @req-REQ-0018 @ac-AC-0223
    Example: Can Start Planning Rejected If Locked
      Given the pytest test setup is prepared
      When can start planning rejected if locked is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0224
    Example: Can Start Planning Rejected If Wrong Stage
      Given the pytest test setup is prepared
      When can start planning rejected if wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0218
    Example: Can Propose Plan Ok
      Given the pytest test setup is prepared
      When can propose plan ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0217
    Example: Can Propose Plan Denied Wrong Stage
      Given the pytest test setup is prepared
      When can propose plan denied wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0210
    Example: Can Approve Plan Ok
      Given the pytest test setup is prepared
      When can approve plan ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0209
    Example: Can Approve Plan Denied Wrong Stage
      Given the pytest test setup is prepared
      When can approve plan denied wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0222
    Example: Can Start Implementation Ok
      Given the pytest test setup is prepared
      When can start implementation ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0219
    Example: Can Start Implementation Failed Validation Ok
      Given the pytest test setup is prepared
      When can start implementation failed validation ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0221
    Example: Can Start Implementation No Accepted Plan
      Given the pytest test setup is prepared
      When can start implementation no accepted plan is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0220
    Example: Can Start Implementation Locked
      Given the pytest test setup is prepared
      When can start implementation locked is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0211
    Example: Can Finish Implementation Ok
      Given the pytest test setup is prepared
      When can finish implementation ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0212
    Example: Can Finish Implementation Wrong Stage
      Given the pytest test setup is prepared
      When can finish implementation wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0226
    Example: Can Start Validation Ok
      Given the pytest test setup is prepared
      When can start validation ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0227
    Example: Can Start Validation Wrong Stage
      Given the pytest test setup is prepared
      When can start validation wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0225
    Example: Can Start Validation Locked
      Given the pytest test setup is prepared
      When can start validation locked is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0214
    Example: Can Finish Validation Ok
      Given the pytest test setup is prepared
      When can finish validation ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0213
    Example: Can Finish Validation Denied
      Given the pytest test setup is prepared
      When can finish validation denied is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0216
    Example: Can Mark Todo Done User
      Given the pytest test setup is prepared
      When can mark todo done user is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0215
    Example: Can Mark Todo Done Agent Denied
      Given the pytest test setup is prepared
      When can mark todo done agent denied is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0236
    Example: Metadata Edit Decision Wrong Stage
      Given the pytest test setup is prepared
      When metadata edit decision wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0235
    Example: Metadata Edit Decision Locked
      Given the pytest test setup is prepared
      When metadata edit decision locked is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0260
    Example: Todo Add Decision Ok
      Given the pytest test setup is prepared
      When todo add decision ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0259
    Example: Todo Add Decision During Planning
      Given the pytest test setup is prepared
      When todo add decision during planning is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0261
    Example: Todo Add Decision Planning Non User Allowed
      Given the pytest test setup is prepared
      When todo add decision planning non user allowed is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0262
    Example: Todo Add Decision Wrong Stage
      Given the pytest test setup is prepared
      When todo add decision wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0258
    Example: Todo Add Decision Active Stage Blocks
      Given the pytest test setup is prepared
      When todo add decision active stage blocks is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0264
    Example: Todo Toggle Decision Ok
      Given the pytest test setup is prepared
      When todo toggle decision ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0266
    Example: Todo Toggle During Implementation
      Given the pytest test setup is prepared
      When todo toggle during implementation is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0268
    Example: Todo Toggle Validation Denied
      Given the pytest test setup is prepared
      When todo toggle validation denied is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0265
    Example: Todo Toggle Done Denied
      Given the pytest test setup is prepared
      When todo toggle done denied is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0263
    Example: Todo Toggle Cancelled Denied
      Given the pytest test setup is prepared
      When todo toggle cancelled denied is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0267
    Example: Todo Toggle Non User Denied
      Given the pytest test setup is prepared
      When todo toggle non user denied is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0250
    Example: Question Add Ok
      Given the pytest test setup is prepared
      When question add ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0249
    Example: Question Add During Planning User
      Given the pytest test setup is prepared
      When question add during planning user is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0251
    Example: Question Add Planning Non User Allowed
      Given the pytest test setup is prepared
      When question add planning non user allowed is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0253
    Example: Question Add Wrong Stage
      Given the pytest test setup is prepared
      When question add wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0252
    Example: Question Add Wrong Active Stage
      Given the pytest test setup is prepared
      When question add wrong active stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0254
    Example: Question Mutation Ok
      Given the pytest test setup is prepared
      When question mutation ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0256
    Example: Question Mutation Planning User Ok
      Given the pytest test setup is prepared
      When question mutation planning user ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0255
    Example: Question Mutation Planning Non User Allowed
      Given the pytest test setup is prepared
      When question mutation planning non user allowed is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0257
    Example: Question Mutation Wrong Stage
      Given the pytest test setup is prepared
      When question mutation wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0242
    Example: Plan Propose Ok
      Given the pytest test setup is prepared
      When plan propose ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0240
    Example: Plan Propose No Lock
      Given the pytest test setup is prepared
      When plan propose no lock is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0241
    Example: Plan Propose No Run
      Given the pytest test setup is prepared
      When plan propose no run is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0243
    Example: Plan Propose Run Not Running
      Given the pytest test setup is prepared
      When plan propose run not running is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0244
    Example: Plan Propose Wrong Stage
      Given the pytest test setup is prepared
      When plan propose wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0238
    Example: Plan Approve Ok
      Given the pytest test setup is prepared
      When plan approve ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0239
    Example: Plan Approve Wrong Stage
      Given the pytest test setup is prepared
      When plan approve wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0237
    Example: Plan Approve Locked
      Given the pytest test setup is prepared
      When plan approve locked is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0246
    Example: Plan Revise Ok
      Given the pytest test setup is prepared
      When plan revise ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0247
    Example: Plan Revise Wrong Stage
      Given the pytest test setup is prepared
      When plan revise wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0245
    Example: Plan Revise Locked
      Given the pytest test setup is prepared
      When plan revise locked is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0232
    Example: Implementation Mutation Ok
      Given the pytest test setup is prepared
      When implementation mutation ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0230
    Example: Implementation Mutation No Lock
      Given the pytest test setup is prepared
      When implementation mutation no lock is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0231
    Example: Implementation Mutation No Run
      Given the pytest test setup is prepared
      When implementation mutation no run is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0233
    Example: Implementation Mutation Run Not Running
      Given the pytest test setup is prepared
      When implementation mutation run not running is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0234
    Example: Implementation Mutation Wrong Stage
      Given the pytest test setup is prepared
      When implementation mutation wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0229
    Example: Implementation Mutation Lock Run Id Mismatch
      Given the pytest test setup is prepared
      When implementation mutation lock run id mismatch is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0273
    Example: Validation Check Ok
      Given the pytest test setup is prepared
      When validation check ok is executed
      Then decision.ok is True

    @req-REQ-0018 @ac-AC-0271
    Example: Validation Check No Lock
      Given the pytest test setup is prepared
      When validation check no lock is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0272
    Example: Validation Check No Run
      Given the pytest test setup is prepared
      When validation check no run is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0274
    Example: Validation Check Run Not Running
      Given the pytest test setup is prepared
      When validation check run not running is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0275
    Example: Validation Check Wrong Stage
      Given the pytest test setup is prepared
      When validation check wrong stage is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0270
    Example: Validation Check Lock Run Id Mismatch
      Given the pytest test setup is prepared
      When validation check lock run id mismatch is executed
      Then decision.ok is False

    @req-REQ-0018 @ac-AC-0228
    Example: Decision Reason Property
      Given the pytest test setup is prepared
      When decision reason property is executed
      Then d.reason equals 'test msg'

    @req-REQ-0018 @ac-AC-0205
    Example: Active stage requires a matching running run
      Given a task lock identifies an active lifecycle stage
      When the matching run is missing, stopped, or inconsistent
      Then no valid active stage is derived

    @req-REQ-0018 @ac-AC-0248
    Example: Planning can start from plannable stages
      Given a task is draft or awaiting plan review and has no active lock
      When planning permission is evaluated
      Then planning may start

    @req-REQ-0018 @ac-AC-0269
    Example: Unknown actor roles are rejected
      Given an actor role is outside the supported role set
      When policy validation checks the role
      Then the role is rejected
