@area-sidecar_collections @feature-sidecar-collections @generated
Feature: Sidecar Collections

  Derived from current pytest behavior and maintained by SpecMason.

  @rule-sidecar-collections
  Rule: Sidecar Collections

    @req-REQ-0050 @ac-AC-0543
    Example: Todos Links And Requirements Use Per Record Markdown
      Given the pytest test setup is prepared
      When todos links and requirements use per record markdown is executed
      Then 'todos:' is not in task_markdown
      Then 'file_links:' is not in task_markdown
      Then 'requirements:' is not in task_markdown
      Then 'Write sidecar test.' is in todo_text
      Then 'object_type: todo' is in todo_text
      Then 'README.md' is in link_text
      Then 'object_type: link' is in link_text
      Then 'task-0001' is in req_text
      Then 'object_type: requirement' is in req_text
      Then result.exit_code equals 0
      Then 'sidecar-task' is in result.output
