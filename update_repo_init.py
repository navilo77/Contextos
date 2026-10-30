path = r"D:\navil\TCH\CONTEXTOS\Context-OS\app\db\repositories\__init__.py"
with open(path) as f:
    content = f.read()
if "agent_tasks" not in content:
    content += "\nfrom app.db.repositories.agent_tasks import (\n    create_task,\n    get_task,\n    grant_context_access,\n    link_task_requirement,\n    submit_evidence,\n    transition_task_status,\n    verify_evidence,\n)\n"
    content = content.replace('    "require_explicit_transaction",\n]', '    "require_explicit_transaction",\n    "create_task",\n    "get_task",\n    "grant_context_access",\n    "link_task_requirement",\n    "submit_evidence",\n    "transition_task_status",\n    "verify_evidence",\n]')
    with open(path, 'w') as f:
        f.write(content)
    print("ok")
else:
    print("exists")
