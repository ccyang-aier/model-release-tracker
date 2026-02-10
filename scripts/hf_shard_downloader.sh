#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# 交互式 HuggingFace / hf-mirror 模型分片下载脚本
#
# 目标：
# - 支持按“分片范围”串行下载 HuggingFace 模型（或 hf-mirror 镜像）
# - 使用 wget 分片下载，并支持断点续传（wget -c）
#
# 适用场景：
# - 超大模型被拆分为大量分片文件，例如：
#   model-00001-of-000163.safetensors
#
# 设计约定（与用户需求一致）：
# - 分片范围使用 "start:end" 形式，采用左闭右开区间：
#   5:25 表示下载第 5 ~ 24 个分片（分片编号从 1 开始）
# - 必填参数：模型名、总分片数（交互输入，不通过命令行参数）
# - 下载源可选：huggingface（默认）或 hf-mirror
#   - 当选择 hf-mirror 时，会在脚本内设置：
#     export HF_ENDPOINT=https://hf-mirror.com
#
# 注意：
# - 若下载私有仓库或受限文件，可在运行脚本前设置 HF_TOKEN 环境变量，
#   脚本会自动将其作为 Bearer Token 注入 wget 请求头。
###############################################################################

_die() {
  echo "[ERROR] $*" 1>&2
  exit 1
}

_trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf "%s" "$s"
}

_prompt() {
  local label="$1"
  local default_value="${2-}"
  local input=""

  if [[ -n "${default_value}" ]]; then
    read -r -p "${label}（默认：${default_value}）： " input || true
    input="$(_trim "${input}")"
    if [[ -z "${input}" ]]; then
      printf "%s" "${default_value}"
    else
      printf "%s" "${input}"
    fi
    return 0
  fi

  read -r -p "${label}： " input || true
  printf "%s" "$(_trim "${input}")"
}

_prompt_required() {
  local label="$1"
  local v=""
  while true; do
    v="$(_prompt "${label}")"
    if [[ -n "${v}" ]]; then
      printf "%s" "${v}"
      return 0
    fi
    echo "[WARN] 该项必填，请重新输入。"
  done
}

_prompt_yes_no() {
  local label="$1"
  local default_yn="$2" # y / n
  local v=""
  while true; do
    v="$(_prompt "${label} [y/n]" "${default_yn}")"
    case "${v}" in
      y|Y) printf "y"; return 0 ;;
      n|N) printf "n"; return 0 ;;
      *) echo "[WARN] 请输入 y 或 n。" ;;
    esac
  done
}

_is_int() {
  [[ "${1}" =~ ^[0-9]+$ ]]
}

_parse_range_left_closed_right_open() {
  # 输入：range_s, total
  # 输出：全局变量 RANGE_START, RANGE_END（end 为“右开”边界）
  local range_s="$1"
  local total="$2"

  if [[ ! "${range_s}" =~ ^[0-9]+:[0-9]+$ ]]; then
    _die "分片范围格式错误：${range_s}，应为 start:end，例如 5:25（左闭右开）。"
  fi

  local start="${range_s%%:*}"
  local end="${range_s##*:}"

  if ! _is_int "${start}" || ! _is_int "${end}"; then
    _die "分片范围必须为整数：${range_s}"
  fi

  start=$((10#${start}))
  end=$((10#${end}))
  total=$((10#${total}))

  if (( start < 1 )); then
    _die "分片起始编号必须 >= 1，当前为：${start}"
  fi
  if (( end <= start )); then
    _die "分片范围必须满足 end > start（左闭右开），当前为：${range_s}"
  fi
  if (( end > total + 1 )); then
    _die "分片范围右边界 end 不能超过 total+1（${total}+1），当前为：${end}"
  fi

  RANGE_START="${start}"
  RANGE_END="${end}"
}

_resolve_base_url() {
  # 输入：source, org, model, revision
  # 输出：打印 base_url（以 / 结尾）
  local source="$1"
  local org="$2"
  local model="$3"
  local revision="$4"

  case "${source}" in
    huggingface)
      printf "https://huggingface.co/%s/%s/resolve/%s/" "${org}" "${model}" "${revision}"
      ;;
    hf-mirror)
      printf "https://hf-mirror.com/%s/%s/resolve/%s/" "${org}" "${model}" "${revision}"
      ;;
    *)
      _die "未知下载源：${source}（仅支持 huggingface 或 hf-mirror）"
      ;;
  esac
}

_build_shard_filename() {
  # 输入：prefix, idx, total, idx_pad, total_pad, ext
  local prefix="$1"
  local idx="$2"
  local total="$3"
  local idx_pad="$4"
  local total_pad="$5"
  local ext="$6"

  local idx_s
  local total_s
  idx_s="$(printf "%0*d" "${idx_pad}" "${idx}")"
  total_s="$(printf "%0*d" "${total_pad}" "${total}")"

  printf "%s-%s-of-%s.%s" "${prefix}" "${idx_s}" "${total_s}" "${ext}"
}

main() {
  echo "================= HF Shard Downloader ================="
  echo "交互式分片下载（wget 串行 + 断点续传）"
  echo

  local source
  source="$(_prompt "选择下载源（huggingface / hf-mirror）" "huggingface")"
  case "${source}" in
    huggingface|hf-mirror) ;;
    *) _die "下载源只能是 huggingface 或 hf-mirror，当前为：${source}" ;;
  esac

  if [[ "${source}" == "hf-mirror" ]]; then
    export HF_ENDPOINT="https://hf-mirror.com"
    echo "[INFO] 已设置环境变量：HF_ENDPOINT=${HF_ENDPOINT}"
  fi

  local default_org="deepseek-ai"
  local org
  org="$(_prompt "组织/用户名（仓库 owner）" "${default_org}")"
  if [[ -z "${org}" ]]; then
    org="${default_org}"
  fi

  local model
  model="$(_prompt_required "模型名（仓库 repo，例如 DeepSeek-R1）")"

  local total
  total="$(_prompt_required "总分片数（例如 163）")"
  _is_int "${total}" || _die "总分片数必须为正整数，当前为：${total}"
  total=$((10#${total}))
  (( total >= 1 )) || _die "总分片数必须 >= 1，当前为：${total}"

  local revision
  revision="$(_prompt "分支/版本（revision，例如 main）" "main")"
  revision="$(_trim "${revision}")"
  [[ -n "${revision}" ]] || revision="main"

  local range_default="1:$((total + 1))"
  local range_s
  range_s="$(_prompt "分片范围（start:end，左闭右开）" "${range_default}")"
  _parse_range_left_closed_right_open "${range_s}" "${total}"

  local out_dir_default="./downloads/${model}"
  local out_dir
  out_dir="$(_prompt "下载输出目录" "${out_dir_default}")"
  out_dir="$(_trim "${out_dir}")"
  [[ -n "${out_dir}" ]] || out_dir="${out_dir_default}"

  local dry_run
  dry_run="$(_prompt_yes_no "是否仅打印将要下载的 URL（dry-run，不实际下载）" "n")"

  local proceed
  proceed="$(_prompt_yes_no "确认开始处理分片下载任务" "y")"
  [[ "${proceed}" == "y" ]] || _die "用户取消。"

  if [[ "${dry_run}" != "y" ]]; then
    command -v wget >/dev/null 2>&1 || _die "未找到 wget，请先安装 wget。"
  fi

  mkdir -p "${out_dir}"

  local base_url
  base_url="$(_resolve_base_url "${source}" "${org}" "${model}" "${revision}")"

  local file_prefix="model"
  local file_ext="safetensors"

  local idx_pad=5
  local total_pad=6
  local total_digits="${#total}"
  if (( total_digits > total_pad )); then
    total_pad="${total_digits}"
  fi
  local idx_digits="${#total}"
  if (( idx_digits > idx_pad )); then
    idx_pad="${idx_digits}"
  fi

  echo
  echo "[INFO] base_url=${base_url}"
  echo "[INFO] 分片范围（左闭右开）：${RANGE_START}:${RANGE_END}（将下载 $((RANGE_END - RANGE_START)) 个分片）"
  echo "[INFO] 输出目录：${out_dir}"
  if [[ -n "${HF_TOKEN-}" ]]; then
    echo "[INFO] 检测到 HF_TOKEN，将作为 Bearer Token 注入下载请求头。"
  fi
  echo

  local i
  for (( i = RANGE_START; i < RANGE_END; i++ )); do
    local filename
    filename="$(_build_shard_filename "${file_prefix}" "${i}" "${total}" "${idx_pad}" "${total_pad}" "${file_ext}")"

    local url="${base_url}${filename}"
    local dest="${out_dir}/${filename}"

    echo "----------"
    echo "[INFO] shard=${i}/${total} file=${filename}"
    echo "[INFO] url=${url}"

    if [[ "${dry_run}" == "y" ]]; then
      echo "[DRY-RUN] wget -c -O \"${dest}\" \"${url}\""
      continue
    fi

    local -a wget_args
    wget_args=(
      --continue
      --tries=5
      --waitretry=2
      --timeout=30
      --read-timeout=30
      --show-progress
      --progress=bar:force
      -O "${dest}"
    )

    if [[ -n "${HF_TOKEN-}" ]]; then
      wget_args+=( --header "Authorization: Bearer ${HF_TOKEN}" )
    fi

    wget "${wget_args[@]}" "${url}"
  done

  echo
  echo "[DONE] 处理完成。"
}

main "$@"
