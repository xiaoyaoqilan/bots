#!/bin/bash

# 交易策略系统平台 - 停止脚本
# 快速停止 run_monitor.py 和 SocketIO 服务器

echo "🛑 正在停止交易策略系统平台..."

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# 增强的进程停止函数
stop_process() {
    local pid=$1
    local name=$2
    
    if [[ -n $pid ]] && [[ $pid =~ ^[0-9]+$ ]]; then
        if kill -0 $pid 2>/dev/null; then
            log_info "正在停止 $name 进程 (PID: $pid)..."
            
            # 尝试优雅停止 (SIGTERM)
            kill -TERM $pid 2>/dev/null
            sleep 3
            
            # 检查进程是否还在运行
            if kill -0 $pid 2>/dev/null; then
                log_warn "进程未响应，尝试强制终止..."
                kill -KILL $pid 2>/dev/null
                sleep 1
            fi
            
            # 最终检查
            if kill -0 $pid 2>/dev/null; then
                log_error "❌ 无法停止 $name 进程"
                return 1
            else
                log_info "✅ $name 进程已停止"
                return 0
            fi
        else
            log_info "$name 进程已经停止"
            return 0
        fi
    else
        log_debug "无效的PID: $pid"
        return 1
    fi
}

# 按进程名停止
stop_process_by_name() {
    local process_name=$1
    local description=$2
    
    log_info "查找 $description 进程..."
    
    # 查找匹配的进程
    local pids=$(pgrep -f "$process_name")
    
    if [[ -n $pids ]]; then
        for pid in $pids; do
            local cmdline=$(ps -p $pid -o command= 2>/dev/null)
            log_debug "找到进程: PID=$pid, CMD=$cmdline"
            stop_process $pid "$description"
        done
    else
        log_info "未找到 $description 进程"
    fi
}

# 清理端口占用
cleanup_port() {
    local port=$1
    local description=$2
    
    log_info "检查端口 $port ($description)..."
    
    # 查找占用端口的进程
    local pids=$(lsof -ti:$port 2>/dev/null)
    
    if [[ -n $pids ]]; then
        log_warn "端口 $port 被占用，正在清理..."
        for pid in $pids; do
            local cmdline=$(ps -p $pid -o command= 2>/dev/null || echo "未知进程")
            log_debug "占用端口 $port 的进程: PID=$pid, CMD=$cmdline"
            
            # 尝试优雅停止
            if kill -TERM $pid 2>/dev/null; then
                sleep 2
                # 如果还在运行，强制停止
                if kill -0 $pid 2>/dev/null; then
                    kill -KILL $pid 2>/dev/null
                fi
            fi
        done
        
        # 再次检查端口
        if lsof -ti:$port >/dev/null 2>&1; then
            log_error "❌ 端口 $port 仍被占用"
        else
            log_info "✅ 端口 $port 已清理"
        fi
    else
        log_info "端口 $port 未被占用"
    fi
}

# 主停止逻辑
main_stop() {
    echo ""
    echo "=============================================="
    echo "🔍 检测运行中的服务..."
    echo "=============================================="
    
    # 1. 从PID文件停止进程
    log_info "检查PID文件..."
    
    if [[ -f .backend.pid ]]; then
        BACKEND_PID=$(cat .backend.pid 2>/dev/null)
        if [[ -n $BACKEND_PID ]]; then
            stop_process $BACKEND_PID "后端监控服务(PID文件)"
        fi
    fi
    
    if [[ -f .frontend.pid ]]; then
        FRONTEND_PID=$(cat .frontend.pid 2>/dev/null)
        if [[ -n $FRONTEND_PID ]]; then
            stop_process $FRONTEND_PID "前端开发服务器(PID文件)"
        fi
    fi
    
    # 2. 按进程名停止 run_monitor.py
    log_info "查找并停止 run_monitor.py 进程..."
    stop_process_by_name "run_monitor.py" "监控系统主进程"
    
    # 3. 停止所有相关的Python进程
    log_info "查找其他相关Python进程..."
    stop_process_by_name "enhanced_monitoring_service" "增强监控服务"
    stop_process_by_name "terminal_monitor.py" "终端监控客户端"
    
    # 4. 清理关键端口
    echo ""
    echo "=============================================="
    echo "🧹 清理端口占用..."
    echo "=============================================="
    
    # SocketIO服务器端口
    cleanup_port 8765 "SocketIO服务器"
    
    # Vue前端开发服务器端口  
    cleanup_port 5173 "Vue前端开发服务器"
    
    # API网关端口
    cleanup_port 8000 "API网关"
    
    # 额外检查其他可能的端口
    cleanup_port 3000 "备用前端端口"
    cleanup_port 8080 "备用后端端口"
    
    # 5. 清理临时文件
    echo ""
    echo "=============================================="
    echo "🗑️  清理临时文件..."
    echo "=============================================="
    
    log_info "清理PID文件..."
    rm -f .backend.pid .frontend.pid 2>/dev/null
    
    log_info "清理临时Socket文件..."
    rm -f /tmp/trading_system_*.sock 2>/dev/null
    
    # 6. 最终检查
    echo ""
    echo "=============================================="
    echo "🔍 最终验证..."
    echo "=============================================="
    
    # 检查是否还有相关进程在运行
    remaining_processes=$(pgrep -f "run_monitor\|enhanced_monitoring\|terminal_monitor" 2>/dev/null)
    if [[ -n $remaining_processes ]]; then
        log_warn "发现残留进程:"
        for pid in $remaining_processes; do
            cmdline=$(ps -p $pid -o command= 2>/dev/null || echo "未知")
            echo "   PID: $pid, CMD: $cmdline"
        done
        echo ""
        read -p "是否强制终止这些进程? (y/N): " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            for pid in $remaining_processes; do
                kill -KILL $pid 2>/dev/null
                log_info "强制终止进程 $pid"
            done
        fi
    else
        log_info "✅ 没有发现残留进程"
    fi
    
    # 检查关键端口是否已清理
    for port in 8765 5173 8000; do
        if lsof -ti:$port >/dev/null 2>&1; then
            log_warn "⚠️  端口 $port 仍被占用"
        fi
    done
}

# 显示帮助信息
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -h, --help     显示帮助信息"
    echo "  -f, --force    强制停止所有相关进程"
    echo "  -q, --quiet    静默模式，减少输出"
    echo "  -v, --verbose  详细模式，显示调试信息"
    echo ""
    echo "示例:"
    echo "  $0              # 正常停止"
    echo "  $0 -f           # 强制停止"
    echo "  $0 -v           # 详细模式停止"
}

# 解析命令行参数
FORCE_MODE=false
QUIET_MODE=false
VERBOSE_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -f|--force)
            FORCE_MODE=true
            shift
            ;;
        -q|--quiet)
            QUIET_MODE=true
            shift
            ;;
        -v|--verbose)
            VERBOSE_MODE=true
            shift
            ;;
        *)
            log_error "未知选项: $1"
            show_help
            exit 1
            ;;
    esac
done

# 如果是静默模式，重定向输出
if [[ $QUIET_MODE == true ]]; then
    exec > /dev/null 2>&1
fi

# 开始停止流程
echo ""
echo "🛑 交易策略系统平台 - 停止脚本"
echo "当前时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 如果是强制模式，直接杀死所有相关进程
if [[ $FORCE_MODE == true ]]; then
    log_warn "🔥 强制模式：直接终止所有相关进程"
    
    # 强制终止所有相关Python进程
    pkill -f "run_monitor\|enhanced_monitoring\|terminal_monitor" 2>/dev/null
    
    # 强制清理所有相关端口
    for port in 8765 5173 8000 3000 8080; do
        lsof -ti:$port | xargs kill -9 2>/dev/null
    done
    
    # 清理文件
    rm -f .backend.pid .frontend.pid 2>/dev/null
    rm -f /tmp/trading_system_*.sock 2>/dev/null
    
    log_info "✅ 强制停止完成"
else
    # 正常停止流程
    main_stop
fi

# 显示最终状态
echo ""
echo "=============================================="
echo -e "${GREEN}✅ 交易策略系统平台已停止${NC}"
echo "=============================================="
echo ""

# 显示日志文件位置
if [[ $QUIET_MODE == false ]]; then
    echo -e "${YELLOW}📁 日志文件位置:${NC}"
    if [[ -f logs/trading_system.log ]]; then
        echo "   系统日志: logs/trading_system.log"
    fi
    if [[ -f logs/error.log ]]; then
        echo "   错误日志: logs/error.log"
    fi
    if [[ -f backend.log ]]; then
        echo "   后端日志: backend.log"
    fi
    if [[ -f frontend.log ]]; then
        echo "   前端日志: frontend.log"
    fi
    echo ""
    echo -e "${GREEN}💡 重新启动系统:${NC} python3 run_monitor.py"
    echo -e "${GREEN}💡 查看系统状态:${NC} ps aux | grep -E '(run_monitor|enhanced_monitoring)'"
    echo -e "${GREEN}💡 检查端口状态:${NC} lsof -i :8765,5173,8000"
    echo ""
fi

exit 0 