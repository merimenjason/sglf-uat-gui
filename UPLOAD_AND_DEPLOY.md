# Upload and deploy

## Upload to GitHub

1. Create a folder named `travel-claims-streamlit` and extract `travel-claims-streamlit.zip` into it.
2. Create a new GitHub repository and set its visibility to **Private**.
3. In the empty repository, select **Add file > Upload files**.
4. Upload the **contents** of the extracted `travel-claims-streamlit` folder.
5. Before committing, confirm that these files are visible at the repository root:

```text
streamlit_app.py
singlife_travel_claim.py
requirements.txt
packages.txt
README.md
.streamlit/config.toml
assets/favicon.png
sample_dummy_docs/
```

6. Commit the files to the `main` branch.

Do not upload a `.venv` folder, a local `secrets.toml`, browser downloads, logs, or screenshots.

## Deploy to Streamlit Community Cloud

1. Sign in at [share.streamlit.io](https://share.streamlit.io/) with GitHub.
2. Select **Create app** and choose the private repository.
3. Set the branch to `main`.
4. Set the entrypoint to `streamlit_app.py`.
5. Under **Advanced settings**, select Python 3.12.
6. Leave secrets empty; the packaged app has no credentials.
7. Deploy and wait for the dependency installation to finish.
8. Keep the app private and add only approved QA viewers.

## First test

1. Open the deployed app.
2. Change the preselected **Submit to UAT** action to **Review before submission**.
3. Choose **Medical expense**.
4. Press **Prepare review**.
5. Confirm the run reaches only the Merimen UAT hostname and does not confirm the final submission.
6. Confirm the **Live browser** panel refreshes as the script reaches each checkpoint.
7. Review the private technical log and any failure screenshot.

The UI defaults to **Submit to UAT**, but the button stays disabled until the dummy-data/UAT checkbox is selected. Only use it after review mode has completed successfully and the team has reconfirmed that the portal is UAT.
