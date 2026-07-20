@area-task_markdown_export @feature-task-markdown-export @generated
Feature: Task Markdown Export

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-task-markdown-export
  Rule: Task Markdown Export

    @req-REQ-0060 @ac-AC-0643
    Example: Task Export Includes Curated Report And Raw Task Files
      Given the pytest test setup is prepared
      When task export includes curated report and raw task files is executed
      Then isinstance succeeds
      Then '# Compiled Task Export:' is in content
      Then '## Curated Task Report' is in content
      Then '## Raw Taskledger Record Files' is in content
      Then 'task.md' is in content
      Then 'plans/' is in content
      Then isinstance succeeds

    @req-REQ-0060 @ac-AC-0644
    Example: Task Export Includes Source File Snapshots From Changes
      Given the pytest test setup is prepared
      When task export includes source file snapshots from changes is executed
      Then isinstance succeeds
      Then '## Source File Snapshots' is in content
      Then '# Test Project' is in content

    @req-REQ-0060 @ac-AC-0647
    Example: Task Export No Source Files Skips Source Snapshot Section
      Given the pytest test setup is prepared
      When task export no source files skips source snapshot section is executed
      Then isinstance succeeds
      Then '## Source File Snapshots' is not in content
      Then '# Test Project' is not in content

    @req-REQ-0060 @ac-AC-0650
    Example: Task Export Skips Outside Workspace File
      Given the pytest test setup is prepared
      When task export skips outside workspace file is executed
      Then isinstance succeeds
      Then isinstance succeeds
      Then '/etc/passwd' is in paths

    @req-REQ-0060 @ac-AC-0651
    Example: Task Export Skips Oversized Source File
      Given the pytest test setup is prepared
      When task export skips oversized source file is executed
      Then isinstance succeeds
      Then isinstance succeeds
      Then 'bigfile.txt' is in reasons_by_path

    @req-REQ-0060 @ac-AC-0639
    Example: Task Export Does Not Mutate Taskledger State
      Given the pytest test setup is prepared
      When task export does not mutate taskledger state is executed
      Then before equals after

    @req-REQ-0060 @ac-AC-0642
    Example: Task Export Front Matter Contains Metadata
      Given the pytest test setup is prepared
      When task export front matter contains metadata is executed
      Then isinstance succeeds
      Then 'object_type: task_markdown_export' is in content
      Then 'export_version: 1' is in content
      Then 'taskledger_version:' is in content
      Then 'include_source_files: True' is in content

    @req-REQ-0060 @ac-AC-0638
    Example: Task Export Deterministic Body
      Given the pytest test setup is prepared
      When task export deterministic body is executed
      Then isinstance succeeds
      Then isinstance succeeds
      Then body1 equals body2

    @req-REQ-0060 @ac-AC-0653
    Example: Task Export Summary Table
      Given the pytest test setup is prepared
      When task export summary table is executed
      Then isinstance succeeds
      Then '## Export Summary' is in content
      Then '| Record files included |' is in content
      Then '| Source files included |' is in content

    @req-REQ-0060 @ac-AC-0637
    Example: Task Export Dedupes Change And Plan Source Paths
      Given the pytest test setup is prepared
      When task export dedupes change and plan source paths is executed
      Then isinstance succeeds

    @req-REQ-0060 @ac-AC-0649
    Example: Task Export Skips Nested Git Directory
      Given the pytest test setup is prepared
      When task export skips nested git directory is executed
      Then isinstance succeeds
      Then 'should not be exported' is not in content
      Then isinstance succeeds
      Then any succeeds

    @req-REQ-0060 @ac-AC-0641
    Example: Task Export Does Not Report Missing Plan Only Source File
      Given the pytest test setup is prepared
      When task export does not report missing plan only source file is executed
      Then isinstance succeeds
      Then all succeeds

    @req-REQ-0060 @ac-AC-0640
    Example: Task Export Does Not Report Git Scan Dot As Source File
      Given the pytest test setup is prepared
      When task export does not report git scan dot as source file is executed
      Then isinstance succeeds
      Then all succeeds

    @req-REQ-0060 @ac-AC-0655
    Example: Task Export Writes Markdown File
      Given the pytest test setup is prepared
      When task export writes markdown file is executed
      Then exit_code equals 0
      Then 'wrote task export' is in stdout
      Then '# Compiled Task Export:' is in content
      Then '## Raw Taskledger Record Files' is in content

    @req-REQ-0060 @ac-AC-0652
    Example: Task Export Stdout Markdown
      Given the pytest test setup is prepared
      When task export stdout markdown is executed
      Then exit_code equals 0
      Then '# Compiled Task Export:' is in stdout
      Then '## Raw Taskledger Record Files' is in stdout

    @req-REQ-0060 @ac-AC-0645
    Example: Task Export Json Output Writes File
      Given the pytest test setup is prepared
      When task export json output writes file is executed
      Then exit_code equals 0
      Then '# Compiled Task Export:' is in file_content

    @req-REQ-0060 @ac-AC-0654
    Example: Task Export Uses Active Task Default
      Given the pytest test setup is prepared
      When task export uses active task default is executed
      Then exit_code equals 0

    @req-REQ-0060 @ac-AC-0646
    Example: Task Export No Source Files Flag
      Given the pytest test setup is prepared
      When task export no source files flag is executed
      Then exit_code equals 0
      Then '## Source File Snapshots' is not in stdout

    @req-REQ-0060 @ac-AC-0648
    Example: Task Export Positional Task Ref
      Given the pytest test setup is prepared
      When task export positional task ref is executed
      Then exit_code equals 0
      Then 'wrote task export' is in stdout
