"""Upload the Databricks notebooks (pipeline/ and ml/) to the workspace and optionally
run one as a one-off serverless job.

    python -m tools.deploy                         # upload all notebooks
    python -m tools.deploy --run 00_setup          # upload, then run 00_setup and wait
    python -m tools.deploy --run 02_silver 03_gold # run several in order

Workspace layout:  /Users/<you>/gridwise/pipeline/<name>   and   /Users/<you>/gridwise/ml/<name>
"""
import argparse
import base64

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs, workspace

from ingestion.config import ROOT, get_settings

NOTEBOOK_DIRS = ["pipeline", "ml"]


def remote_root(w: WorkspaceClient) -> str:
    return f"/Users/{w.current_user.me().user_name}/gridwise"


def upload(w: WorkspaceClient) -> dict[str, str]:
    """Upload every notebook; return {notebook_name: workspace_path}."""
    root = remote_root(w)
    paths = {}
    for folder in NOTEBOOK_DIRS:
        target = f"{root}/{folder}"
        w.workspace.mkdirs(target)
        for nb in sorted((ROOT / folder).glob("[0-9]*.py")):
            path = f"{target}/{nb.stem}"
            w.workspace.import_(
                path=path,
                content=base64.b64encode(nb.read_bytes()).decode(),
                format=workspace.ImportFormat.SOURCE,
                language=workspace.Language.PYTHON,
                overwrite=True,
            )
            paths[nb.stem] = path
            print(f"  uploaded {path}")
    return paths


def run(w: WorkspaceClient, path: str, name: str, params: dict) -> str | None:
    print(f"Running {name} on serverless ...")
    r = w.jobs.submit(
        run_name=f"gridwise-{name}",
        tasks=[jobs.SubmitTask(
            task_key=name.replace(".", "_"),
            notebook_task=jobs.NotebookTask(notebook_path=path, base_parameters=params),
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
    p.add_argument("--run", nargs="*", default=[], help="notebook names, e.g. 01_bronze 05_predict")
    args = p.parse_args()
    s = get_settings()
    w = WorkspaceClient(host=s.databricks_host, token=s.databricks_token)
    paths = upload(w)
    for name in args.run:
        if name not in paths:
            raise SystemExit(f"unknown notebook '{name}'. Available: {', '.join(sorted(paths))}")
        result = run(w, paths[name], name, {"catalog": s.catalog})
        if result:
            print(f"  output: {result}")


if __name__ == "__main__":
    main()
