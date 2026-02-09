from __future__ import annotations

from pydantic import BaseModel
from typing import List, Optional


class SearchRequest(BaseModel):
    query: str
    count: int = 5


class SearchResult(BaseModel):
    name: str
    url: str
    snippet: str


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    model: str
    error: Optional[str] = None
    cached: Optional[bool] = None
    retry_after_s: Optional[int] = None


class PowerTelemetry(BaseModel):
    watts: Optional[float]
    plugged: Optional[bool]
    percent: Optional[float]
    status: str
    detail: Optional[str] = None
    timestamp: str
    ram_used_bytes: Optional[int] = None
    ram_total_bytes: Optional[int] = None
    ram_percent: Optional[float] = None
    cpu_temp_c: Optional[float] = None
    temp_source: Optional[str] = None
    cpu_usage_percent: Optional[float] = None
    power_idle_watts: Optional[float] = None
    power_max_watts: Optional[float] = None
    power_utilization: Optional[float] = None
    vram_used_bytes: Optional[int] = None
    vram_total_bytes: Optional[int] = None
    vram_percent: Optional[float] = None
    vram_source: Optional[str] = None
    gpu_driver: Optional[str] = None
    vulkan_available: Optional[bool] = None


class ModelInfo(BaseModel):
    name: str
    path: str
    size_bytes: int
    size_human: str
    is_current: bool
    gguf_model_name: Optional[str] = None
    gguf_architecture: Optional[str] = None
    gguf_file_type: Optional[int] = None
    quantization: Optional[str] = None


class ModelsResponse(BaseModel):
    models: List[ModelInfo]
    current_model: Optional[str]
    model_dir: str


class SwitchModelRequest(BaseModel):
    model_path: str


class SwitchModelResponse(BaseModel):
    success: bool
    message: str
    new_model: Optional[str] = None


class ModelDirRequest(BaseModel):
    path: str


class ModelDirResponse(BaseModel):
    success: bool
    message: str
    model_dir: Optional[str] = None


class FilesDirRequest(BaseModel):
    path: str
    create: bool = True


class FilesDirResponse(BaseModel):
    success: bool
    message: str
    files_dir: Optional[str] = None
    writable: Optional[bool] = None


class FilesListRequest(BaseModel):
    path: str = "."
    recursive: bool = False
    limit: int = 200


class FilesListEntry(BaseModel):
    path: str
    is_dir: bool
    size_bytes: Optional[int] = None
    mtime_epoch: Optional[float] = None


class FilesListResponse(BaseModel):
    root: str
    base: str
    entries: List[FilesListEntry]
    truncated: bool = False


class FilesReadRequest(BaseModel):
    path: str
    max_bytes: Optional[int] = None


class FilesReadResponse(BaseModel):
    root: str
    path: str
    content: str
    truncated: bool
    bytes_read: int


class FilesWriteRequest(BaseModel):
    path: str
    content: str
    overwrite: bool = False
    mkdirs: bool = True


class FilesWriteResponse(BaseModel):
    root: str
    path: str
    bytes_written: int
    message: str
    backup_path: Optional[str] = None


class FilesSearchRequest(BaseModel):
    query: str
    path: str = "."
    limit: int = 50
    regex: bool = False
    case_sensitive: bool = False


class FilesSearchMatch(BaseModel):
    path: str
    line: int
    column: Optional[int] = None
    text: str


class FilesSearchResponse(BaseModel):
    root: str
    base: str
    query: str
    matches: List[FilesSearchMatch]
    truncated: bool = False


class LlamaCtxRequest(BaseModel):
    ctx_size: int
    restart: bool = True


class LlamaCtxResponse(BaseModel):
    success: bool
    message: str
    ctx_size: Optional[int] = None
    llama_args: Optional[str] = None
    restarted: bool = False
    pid: Optional[int] = None
    model: Optional[str] = None


class LlamaStatusResponse(BaseModel):
    running: bool
    pid: Optional[int] = None
    model: Optional[str] = None
    cmdline: Optional[str] = None
    llama_args_running: Optional[str] = None
    llama_args_configured: Optional[str] = None
    ctx_size_running: Optional[int] = None
    ctx_size_configured: Optional[int] = None


class SettingsResponse(BaseModel):
    settings: dict
    settings_file: str


class SettingsUpdateRequest(BaseModel):
    autostart_model: Optional[bool] = None
    power_idle_watts: Optional[float] = None
    power_max_watts: Optional[float] = None
    tool_files_max_bytes: Optional[int] = None
    llama_args: Optional[str] = None

    class Config:
        extra = "forbid"

