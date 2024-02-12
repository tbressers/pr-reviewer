import openai
import git
from pydantic import BaseSettings
import typer
from typing import Optional, List, Dict, Any, Union

class Settings(BaseSettings):
    TOKEN: str
    OPEN_AI_KEY: str = "no_key_needed"
    OWNER: str
    REPO_NAME: str
    PRICE_PER_TOKEN: float = 2.0000000000000002e-07
    MODEL_NAME: str = ""

    class Config:
        env_file = '.env'
        env_prefix = "PR_REVIEW_BOT_"

settings = Settings()

openai.api_key = settings.OPEN_AI_KEY
repo = git.Repo.clone_from(f"https://github.com/{settings.OWNER}/{settings.REPO_NAME}.git", "/tmp/repo", branch="master")

app = typer.Typer()

def get_open_prs() -> List[Any]:
    repo.remotes.origin.fetch()
    open_prs = [pr for pr in repo.iter_commits('origin/master..origin') if pr.message.startswith('Merge pull request')]
    return open_prs


def get_patch(pr_file: Any) -> str:
    return pr_file.patch if pr_file.changes != 0 else 'no changes'

def analyze_pr(pr: Any) -> Dict[str, Union[str, float]]:
    pr_description = pr.body

    # Read all PR files
    pr_files = repo.commit(pr.hexsha).stats.files
    pr_content = "\n\n\n".join(f"filename: {file.filename}: status: {file.status} patch: {get_patch(file)} " for file in pr_files)

    # Read all PR comments
    comments = repo.commit(pr.hexsha).message.split('\n')[1:]
    pr_comments = "\n".join(comment.body for comment in comments)

    text = f"pr_description\n {pr_description}, \npr_content\n = {pr_content}, \npr_comments\n = {pr_comments}"

    messages = [
        {"role": "system", "content": "You are github PR reviwer assistant."},
        {"role": "user", "content": f"Analyze this pull request text and provide a review:\n\n{text}"}
    ]

    response = openai.ChatCompletion.create(
        model=settings.MODEL_NAME,
        messages=messages,
    )

    review_cost = response['usage']['total_tokens'] * settings.PRICE_PER_TOKEN
    review = response.choices[0].message['content'].strip()
    review = f"Review from GPT \n\n{review}\n \n\nReview costs \n\n{review_cost} USD"

    event = "COMMENT"

    if "approve" in review.lower():
        event = "APPROVE"
    elif "request changes" in review.lower():
        event = "REQUEST_CHANGES"

    return {
        'body': review,
        'event': event
    }

def submit_review(pr: Any, review: Dict[str, Union[str, float]], label_name: str = "pr_review_bot") -> None:
    pr_number = pr.number

    # Create the label if it doesn't exist
    labels = ghapi.issues.list_labels_for_repo()
    if not any(label.name == label_name for label in labels):
        repo.create_head(label_name, commit=pr.hexsha)

    # Add the label to the PR
    repo.git.checkout(label_name)

    # Submit the review
    repo.git.commit('-m', review['body'])
    repo.git.push('origin', label_name)

@app.command()
def review_all_open_pr() -> None:
    open_prs = get_open_prs()
    for pr in open_prs:
        review = analyze_pr(pr)
        if review:
            submit_review(pr, review)
            typer.echo(f"Review submitted for PR #{pr.number}")

@app.command()
def review_pr(pr_number: Optional[int] = typer.Argument(None)) -> None:
    if pr_number is not None:
        pr = ghapi.pulls.get(pr_number)
        review = analyze_pr(pr)
        if review:
            submit_review(pr, review)
            typer.echo(f"Review submitted for PR #{pr.number}")
    else:
        typer.echo("Please provide a valid PR number.")

if __name__ == "__main__":
    app()
