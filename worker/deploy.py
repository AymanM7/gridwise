"""Upload notebooks/ to the Databricks workspace and optionally run one as a one-off
serverless job.

    python -m worker.deploy                      # upload all notebooks
    python -m worker.deploy --run 00_setup       # upload, then run 00_setup and wait
"""
import argparse
import base64

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs, workspace

from .config import ROOT, get_settings


def remote_dir(w: WorkspaceClient) -> str:
    return f"/Users/{w.current_user.me().user_name}/gridwise/notebooks"


def upload(w: WorkspaceClient) -> str:
    target = remote_dir(w)
    w.workspace.mkdirs(target)
    for nb in sorted((ROOT / "notebooks").glob("*.py")):
        w.workspace.import_(
            path=f"{target}/{nb.stem}",
            content=base64.b64encode(nb.read_bytes()).decode(),
            format=workspace.ImportFormat.SOURCE,
            language=workspace.Language.PYTHON,
            overwrite=True,
        )
        print(f"  uploaded {target}/{nb.stem}")
    return target


def run(w: WorkspaceClient, target: str, name: str, params: dict) -> str | None:
    print(f"Running {name} on serverless ...")
    r = w.jobs.submit(
        run_name=f"gridwise-{name}",
        tasks=[jobs.SubmitTask(
            task_key=name.replace(".", "_"),
            notebook_task=jobs.NotebookTask(notebook_path=f"{target}/{name}", base_parameters=params),
        )],
    ).result()
    task = r.tasks[0]
    print(f"  result: {r.state.result_state}  {r.state.state_message or ''}")
    print(f"  run page: {r.run_page_url}")
    out = w.jobs.get_run_output(task.run_id)
    if out.error:
        print(f"  error: {out.error}")
    return out.notebook_output.result if out.notebook_output else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", nargs="*", default=[])
    args = p.parse_args()
    s = get_settings()
    w = WorkspaceClient(host=s.databricks_host, token=s.databricks_token)
    target = upload(w)
    for name in args.run:
        result = run(w, target, name, {"catalog": s.catalog})
        if result:
            print(f"  output: {result}")


if __name__ == "__main__":
    main()
