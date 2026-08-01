use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;
use std::env;
use std::fs;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::{AppHandle, Manager};

#[derive(Debug, Serialize, Deserialize)]
struct LaunchResult {
    job_dir: String,
    worker_pid: u32,
}

fn project_root() -> Result<PathBuf, String> {
    if let Some(path) = dirs::data_local_dir()
        .map(|base| base.join("MeetingDocuments").join("runtime"))
        .filter(|path| path.join("meeting_transcriber").is_dir())
    {
        return Ok(path);
    }

    if let Ok(value) = env::var("MEETING_TRANSCRIBER_ROOT") {
        let path = PathBuf::from(value);
        if path.join("meeting_transcriber").is_dir() {
            return Ok(path);
        }
    }
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    let root = manifest
        .ancestors()
        .nth(3)
        .ok_or_else(|| "Не удалось определить каталог приложения.".to_string())?
        .to_path_buf();
    if !root.join("meeting_transcriber").is_dir() {
        return Err("Не найден Python-компонент. Укажите MEETING_TRANSCRIBER_ROOT.".to_string());
    }
    Ok(root)
}

fn python_executable(root: &Path) -> Result<PathBuf, String> {
    if let Ok(value) = env::var("MEETING_TRANSCRIBER_PYTHON") {
        let path = PathBuf::from(value);
        if path.is_file() {
            return Ok(path);
        }
    }
    let path = root.join(".venv-win").join("Scripts").join("python.exe");
    if path.is_file() {
        Ok(path)
    } else {
        Err("Не найдено окружение .venv-win. Запустите настройку рабочей станции.".to_string())
    }
}
#[derive(Debug)]
struct WorkstationPaths {
    installer_dir: PathBuf,
    source_root: PathBuf,
    runtime_root: PathBuf,
    state_path: PathBuf,
}

fn copy_runtime_tree(source: &Path, target: &Path) -> Result<(), String> {
    fs::create_dir_all(target).map_err(|error| {
        format!(
            "Could not create runtime directory {}: {error}",
            target.display()
        )
    })?;
    for entry in fs::read_dir(source).map_err(|error| {
        format!(
            "Could not read runtime source {}: {error}",
            source.display()
        )
    })? {
        let entry = entry.map_err(|error| error.to_string())?;
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        let file_type = entry.file_type().map_err(|error| error.to_string())?;
        if file_type.is_dir() {
            copy_runtime_tree(&source_path, &target_path)?;
        } else if file_type.is_file() {
            fs::copy(&source_path, &target_path).map_err(|error| {
                format!(
                    "Could not update runtime file {}: {error}",
                    target_path.display()
                )
            })?;
        }
    }
    Ok(())
}

fn sync_runtime_source(paths: &WorkstationPaths) -> Result<(), String> {
    fs::create_dir_all(&paths.runtime_root).map_err(|error| error.to_string())?;
    for relative in ["meeting_transcriber", "scripts"] {
        copy_runtime_tree(
            &paths.source_root.join(relative),
            &paths.runtime_root.join(relative),
        )?;
    }
    for relative in [
        "run.ps1",
        "run-moss-checkpointed.ps1",
        "run-qwen-checkpointed.ps1",
        "run-speaker-clustering.ps1",
    ] {
        fs::copy(
            paths.source_root.join(relative),
            paths.runtime_root.join(relative),
        )
        .map_err(|error| format!("Could not update runtime file {relative}: {error}"))?;
    }
    fs::copy(
        paths.installer_dir.join("model-catalog.json"),
        paths.runtime_root.join("model-catalog.json"),
    )
    .map_err(|error| format!("Could not update the runtime model catalog: {error}"))?;
    Ok(())
}

fn workstation_paths(app: &AppHandle) -> Result<WorkstationPaths, String> {
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    let development_root = manifest
        .ancestors()
        .nth(3)
        .ok_or_else(|| "Не удалось определить каталог разработки.".to_string())?
        .to_path_buf();
    let development_installer = development_root.join("installer");
    let (installer_dir, source_root, runtime_root) = if development_installer
        .join("Install-Workstation.ps1")
        .is_file()
    {
        (
            development_installer,
            development_root.clone(),
            dirs::data_local_dir()
                .ok_or_else(|| "LocalAppData is unavailable.".to_string())?
                .join("MeetingDocuments")
                .join("runtime"),
        )
    } else {
        let resources = app
            .path()
            .resource_dir()
            .map_err(|error| format!("Не найден каталог ресурсов: {error}"))?;
        (
            resources.join("workstation").join("installer"),
            resources.join("workstation").join("runtime-source"),
            dirs::data_local_dir()
                .ok_or_else(|| "Не найден LocalAppData.".to_string())?
                .join("MeetingDocuments")
                .join("runtime"),
        )
    };
    let state_path = dirs::data_local_dir()
        .ok_or_else(|| "Не найден LocalAppData.".to_string())?
        .join("MeetingDocuments")
        .join("setup-state.json");
    if !installer_dir.join("model-catalog.json").is_file() {
        return Err("Каталог моделей установщика не найден.".to_string());
    }
    Ok(WorkstationPaths {
        installer_dir,
        source_root,
        runtime_root,
        state_path,
    })
}

fn powershell_json(script: &Path, arguments: &[String]) -> Result<Value, String> {
    let mut command = Command::new("powershell.exe");
    command
        .arg("-NoProfile")
        .arg("-ExecutionPolicy")
        .arg("Bypass")
        .arg("-File")
        .arg(script)
        .args(arguments);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let output = command
        .output()
        .map_err(|error| format!("Не удалось запустить проверку: {error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Err(if !stderr.is_empty() { stderr } else { stdout });
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("Проверка вернула некорректный JSON: {error}"))
}

fn workstation_status_value(app: &AppHandle) -> Result<Value, String> {
    let paths = workstation_paths(app)?;
    powershell_json(
        &paths.installer_dir.join("Get-WorkstationStatus.ps1"),
        &[
            "-CatalogPath".to_string(),
            paths
                .installer_dir
                .join("model-catalog.json")
                .to_string_lossy()
                .to_string(),
            "-RuntimeRoot".to_string(),
            paths.runtime_root.to_string_lossy().to_string(),
            "-StatePath".to_string(),
            paths.state_path.to_string_lossy().to_string(),
        ],
    )
}

#[tauri::command]
async fn workstation_status(app: AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || workstation_status_value(&app))
        .await
        .map_err(|error| error.to_string())?
}

fn valid_setup_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 96
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "-_.:".contains(character))
}

#[tauri::command(rename_all = "camelCase")]
async fn start_workstation_setup(
    app: AppHandle,
    pack_id: String,
    model_ids: Vec<String>,
) -> Result<Value, String> {
    if !valid_setup_identifier(&pack_id) {
        return Err("Некорректный идентификатор набора.".to_string());
    }
    let unique: HashSet<&str> = model_ids.iter().map(String::as_str).collect();
    if unique.len() != model_ids.len()
        || model_ids
            .iter()
            .any(|identifier| !valid_setup_identifier(identifier))
    {
        return Err("Некорректный список моделей.".to_string());
    }
    let paths = workstation_paths(&app)?;
    let script = paths.installer_dir.join("Install-Workstation.ps1");
    let catalog = paths.installer_dir.join("model-catalog.json");

    // Plan mode validates the pack and every selected model without changing the PC.
    powershell_json(
        &script,
        &[
            "-Action".to_string(),
            "Plan".to_string(),
            "-PackId".to_string(),
            pack_id.clone(),
            "-ModelIds".to_string(),
            model_ids.join(","),
            "-CatalogPath".to_string(),
            catalog.to_string_lossy().to_string(),
            "-RuntimeRoot".to_string(),
            paths.runtime_root.to_string_lossy().to_string(),
            "-StatePath".to_string(),
            paths.state_path.to_string_lossy().to_string(),
            "-SourceRoot".to_string(),
            paths.source_root.to_string_lossy().to_string(),
        ],
    )?;

    let executable = env::current_exe()
        .map_err(|error| format!("Не найден исполняемый файл приложения: {error}"))?;
    let mut command = Command::new("powershell.exe");
    command
        .arg("-NoProfile")
        .arg("-ExecutionPolicy")
        .arg("Bypass")
        .arg("-File")
        .arg(&script)
        .arg("-Action")
        .arg("Install")
        .arg("-PackId")
        .arg(&pack_id)
        .arg("-ModelIds")
        .arg(model_ids.join(","))
        .arg("-CatalogPath")
        .arg(&catalog)
        .arg("-RuntimeRoot")
        .arg(&paths.runtime_root)
        .arg("-StatePath")
        .arg(&paths.state_path)
        .arg("-SourceRoot")
        .arg(&paths.source_root)
        .arg("-AppExecutable")
        .arg(executable);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let child = command
        .spawn()
        .map_err(|error| format!("Не удалось запустить установку: {error}"))?;
    Ok(serde_json::json!({
        "started": true,
        "process_id": child.id(),
        "state_path": paths.state_path,
        "pack_id": pack_id,
    }))
}

#[tauri::command]
fn open_workstation_setup_log(app: AppHandle) -> Result<(), String> {
    let paths = workstation_paths(&app)?;
    let directory = paths
        .state_path
        .parent()
        .ok_or_else(|| "Не найден каталог установки.".to_string())?;
    fs::create_dir_all(directory)
        .map_err(|error| format!("Не удалось создать каталог журнала: {error}"))?;
    open::that(directory).map_err(|error| format!("Не удалось открыть каталог: {error}"))
}

fn sidecar_json(arguments: &[String]) -> Result<Value, String> {
    let root = project_root()?;
    let python = python_executable(&root)?;
    let mut command = Command::new(python);
    command
        .current_dir(&root)
        .env("PYTHONPATH", &root)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .arg("-m")
        .arg("meeting_transcriber.sidecar")
        .args(arguments);
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let output = command
        .output()
        .map_err(|error| format!("Не удалось запустить обработчик: {error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Err(if !stderr.is_empty() { stderr } else { stdout });
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("Обработчик вернул некорректный ответ: {error}"))
}

#[tauri::command(rename_all = "camelCase")]
async fn system_status(start_ollama: Option<bool>) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut arguments = vec!["system-status".to_string()];
        if start_ollama.unwrap_or(false) {
            arguments.push("--start-ollama".to_string());
        }
        sidecar_json(&arguments)
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
fn default_output_root() -> Result<String, String> {
    let base = dirs::document_dir()
        .or_else(dirs::home_dir)
        .ok_or_else(|| "Не найдена папка Документы.".to_string())?;
    let output = base.join("Документы встреч");
    fs::create_dir_all(&output)
        .map_err(|error| format!("Не удалось создать папку результатов: {error}"))?;
    Ok(output.to_string_lossy().to_string())
}

#[tauri::command(rename_all = "camelCase")]
async fn start_job(
    app: AppHandle,
    input_path: String,
    output_root: String,
    mode: String,
    model: String,
    speaker_count: Option<u8>,
    cloud_consent: bool,
) -> Result<LaunchResult, String> {
    let paths = workstation_paths(&app)?;
    sync_runtime_source(&paths)?;
    tauri::async_runtime::spawn_blocking(move || {
        let mut arguments = vec![
            "launch".to_string(),
            "--input".to_string(),
            input_path,
            "--output-root".to_string(),
            output_root,
            "--mode".to_string(),
            mode,
            "--model".to_string(),
            model,
        ];
        if let Some(count) = speaker_count {
            arguments.push("--speaker-count".to_string());
            arguments.push(count.to_string());
        }
        if cloud_consent {
            arguments.push("--cloud-consent".to_string());
        }
        let value = sidecar_json(&arguments)?;
        serde_json::from_value(value)
            .map_err(|error| format!("Некорректный ответ запуска: {error}"))
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command(rename_all = "camelCase")]
async fn get_job_status(job_dir: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        sidecar_json(&["status".to_string(), "--job-dir".to_string(), job_dir])
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command(rename_all = "camelCase")]
async fn cancel_job(job_dir: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        sidecar_json(&["cancel".to_string(), "--job-dir".to_string(), job_dir]).map(|_| ())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command(rename_all = "camelCase")]
async fn resume_job(app: AppHandle, job_dir: String) -> Result<LaunchResult, String> {
    let paths = workstation_paths(&app)?;
    sync_runtime_source(&paths)?;
    tauri::async_runtime::spawn_blocking(move || {
        let value = sidecar_json(&["resume".to_string(), "--job-dir".to_string(), job_dir])?;
        serde_json::from_value(value)
            .map_err(|error| format!("Некорректный ответ возобновления: {error}"))
    })
    .await
    .map_err(|error| error.to_string())?
}

fn canonical_job_subpath(
    job_dir: &str,
    candidate: Option<&str>,
    required_dir: &str,
) -> Result<PathBuf, String> {
    let job = fs::canonicalize(job_dir).map_err(|_| "Каталог задания не найден.".to_string())?;
    let allowed = fs::canonicalize(job.join(required_dir))
        .map_err(|_| "Каталог результатов ещё не создан.".to_string())?;
    let target = match candidate {
        Some(path) => {
            fs::canonicalize(path).map_err(|_| "Файл результата не найден.".to_string())?
        }
        None => allowed.clone(),
    };
    if !target.starts_with(&allowed) {
        return Err("Приложение может открывать только файлы этого задания.".to_string());
    }
    Ok(target)
}

#[tauri::command(rename_all = "camelCase")]
fn open_document(job_dir: String, document_path: String) -> Result<(), String> {
    let path = canonical_job_subpath(&job_dir, Some(&document_path), "documents")?;
    if !path.is_file() {
        return Err("Документ не найден.".to_string());
    }
    open::that(path).map_err(|error| format!("Не удалось открыть документ: {error}"))
}

#[tauri::command(rename_all = "camelCase")]
fn open_job_folder(job_dir: String) -> Result<(), String> {
    let path = canonical_job_subpath(&job_dir, None, "documents")?;
    open::that(path).map_err(|error| format!("Не удалось открыть папку: {error}"))
}

#[tauri::command(rename_all = "camelCase")]
fn open_logs_folder(job_dir: String) -> Result<(), String> {
    let path = canonical_job_subpath(&job_dir, None, "logs")?;
    open::that(path).map_err(|error| format!("Не удалось открыть журнал: {error}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            system_status,
            default_output_root,
            start_job,
            get_job_status,
            cancel_job,
            resume_job,
            open_document,
            open_job_folder,
            open_logs_folder,
            workstation_status,
            start_workstation_setup,
            open_workstation_setup_log
        ])
        .run(tauri::generate_context!())
        .expect("error while running Meeting Documents");
}
