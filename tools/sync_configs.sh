#!/bin/bash

################################################################################
# 配置文件同步工具
#
# 功能：将主目录的配置文件同步到所有子账户目录
# 作者：网格交易系统
# 日期：2025-11-10
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📖 快速启动指南
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 1️⃣ 基本使用（同步所有配置文件）：
#    cd /Volumes/T7/crypto-trading/tools
#    ./sync_configs.sh
#
# 2️⃣ 同步指定币种（推荐）：
#    ./sync_configs.sh lighter-long-perp-btc.yaml
#
# 3️⃣ 预览模式（查看将要修改什么）：
#    ./sync_configs.sh --dry-run
#
# 4️⃣ 同步前自动备份（安全）：
#    ./sync_configs.sh --backup lighter-long-perp-btc.yaml
#
# 5️⃣ 同步多个币种：
#    ./sync_configs.sh 'lighter-long-perp-{btc,eth,mega}.yaml'
#
# 6️⃣ 只同步到指定账户：
#    ./sync_configs.sh --target zhanghu1,zhanghu3 lighter-long-perp-btc.yaml
#
# 7️⃣ 查看完整帮助：
#    ./sync_configs.sh --help
#
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚙️ 配置说明
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 源目录：/Volumes/T7/crypto-trading/config/grid
# 目标目录：
#   • /Volumes/T7/crypto-trading_zhanghu1/config/grid
#   • /Volumes/T7/crypto-trading_zhanghu2/config/grid
#   • /Volumes/T7/crypto-trading_zhanghu3/config/grid
#   • /Volumes/T7/crypto-trading_zhanghu4/config/grid
#   • /Volumes/T7/crypto-trading_zhanghu5/config/grid
#
# 如需修改目标目录，请编辑下方的 TARGETS 数组
#
################################################################################

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 主目录配置路径
SOURCE_DIR="/Volumes/T7/crypto-trading/config/grid"

# 目标目录列表（子账户目录）
TARGETS=(
    "/Volumes/T7/crypto-trading_zhanghu1/config/grid"
    "/Volumes/T7/crypto-trading_zhanghu2/config/grid"
    "/Volumes/T7/crypto-trading_zhanghu3/config/grid"
    "/Volumes/T7/crypto-trading_zhanghu4/config/grid"
    "/Volumes/T7/crypto-trading_zhanghu5/config/grid"
)

# 备份目录
BACKUP_DIR="/Volumes/T7/config_backups"

################################################################################
# 函数：打印帮助信息
################################################################################
print_help() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  配置文件同步工具 - 使用说明${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${GREEN}用法:${NC}"
    echo -e "  $0 [选项] [文件名]"
    echo ""
    echo -e "${GREEN}选项:${NC}"
    echo -e "  ${YELLOW}-h, --help${NC}          显示此帮助信息"
    echo -e "  ${YELLOW}-a, --all${NC}           同步所有配置文件（默认）"
    echo -e "  ${YELLOW}-d, --dry-run${NC}       预览模式，只显示将要同步的文件"
    echo -e "  ${YELLOW}-b, --backup${NC}        同步前备份目标文件"
    echo -e "  ${YELLOW}-i, --interactive${NC}   交互式确认每个文件"
    echo -e "  ${YELLOW}-t, --target <ID>${NC}   只同步到指定账户（如：zhanghu1,zhanghu3）"
    echo -e "  ${YELLOW}-v, --verbose${NC}       显示详细信息"
    echo ""
    echo -e "${GREEN}示例:${NC}"
    echo -e "  ${BLUE}# 同步所有配置文件${NC}"
    echo -e "  $0"
    echo ""
    echo -e "  ${BLUE}# 只同步BTC配置${NC}"
    echo -e "  $0 lighter-long-perp-btc.yaml"
    echo ""
    echo -e "  ${BLUE}# 同步多个币种${NC}"
    echo -e "  $0 'lighter-long-perp-{btc,eth,mega}.yaml'"
    echo ""
    echo -e "  ${BLUE}# 同步前备份${NC}"
    echo -e "  $0 --backup lighter-long-perp-btc.yaml"
    echo ""
    echo -e "  ${BLUE}# 预览将要同步的文件${NC}"
    echo -e "  $0 --dry-run"
    echo ""
    echo -e "  ${BLUE}# 只同步到账户1和3${NC}"
    echo -e "  $0 --target zhanghu1,zhanghu3 lighter-long-perp-btc.yaml"
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

################################################################################
# 函数：备份文件
################################################################################
backup_file() {
    local file=$1
    local target_dir=$2
    
    if [ -f "$target_dir/$file" ]; then
        # 创建备份目录
        local backup_path="$BACKUP_DIR/$(date +%Y%m%d_%H%M%S)"
        local account_name=$(basename $(dirname $(dirname "$target_dir")))
        local backup_full_path="$backup_path/$account_name"
        
        mkdir -p "$backup_full_path"
        cp "$target_dir/$file" "$backup_full_path/$file"
        
        if [ $VERBOSE -eq 1 ]; then
            echo -e "  ${CYAN}└─ 备份: $backup_full_path/$file${NC}"
        fi
    fi
}

################################################################################
# 函数：同步单个文件到单个目标
################################################################################
sync_file() {
    local file=$1
    local target=$2
    
    # 检查源文件是否存在
    if [ ! -f "$SOURCE_DIR/$file" ]; then
        echo -e "${RED}✗ 源文件不存在: $file${NC}"
        return 1
    fi
    
    # 检查目标目录是否存在
    if [ ! -d "$target" ]; then
        echo -e "${YELLOW}⚠ 目标目录不存在，跳过: $target${NC}"
        return 1
    fi
    
    # 获取账户名称
    local account_name=$(basename $(dirname $(dirname "$target")))
    
    # 如果指定了特定账户，检查是否匹配
    if [ ! -z "$TARGET_ACCOUNTS" ]; then
        if [[ ! ",$TARGET_ACCOUNTS," =~ ",$account_name," ]]; then
            return 0  # 跳过不匹配的账户
        fi
    fi
    
    # 备份模式
    if [ $BACKUP -eq 1 ]; then
        backup_file "$file" "$target"
    fi
    
    # 交互式确认
    if [ $INTERACTIVE -eq 1 ]; then
        echo -e "${YELLOW}? 是否同步到 $account_name/$file? (y/n)${NC}"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            echo -e "${CYAN}  ⊘ 跳过${NC}"
            return 0
        fi
    fi
    
    # 预览模式
    if [ $DRY_RUN -eq 1 ]; then
        echo -e "${CYAN}  → [预览] 将同步到: $account_name/$file${NC}"
        if [ -f "$target/$file" ]; then
            # 显示文件差异
            if command -v diff &> /dev/null; then
                local diff_output=$(diff -q "$SOURCE_DIR/$file" "$target/$file" 2>&1)
                if [ ! -z "$diff_output" ]; then
                    echo -e "${YELLOW}    (文件有差异)${NC}"
                else
                    echo -e "${GREEN}    (文件相同，无需同步)${NC}"
                fi
            fi
        else
            echo -e "${YELLOW}    (目标文件不存在，将创建)${NC}"
        fi
        return 0
    fi
    
    # 实际复制
    cp "$SOURCE_DIR/$file" "$target/$file"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ 同步成功: $account_name/$file${NC}"
        return 0
    else
        echo -e "${RED}  ✗ 同步失败: $account_name/$file${NC}"
        return 1
    fi
}

################################################################################
# 主程序
################################################################################

# 默认参数
DRY_RUN=0
BACKUP=0
INTERACTIVE=0
VERBOSE=0
TARGET_ACCOUNTS=""
FILE_PATTERN=""

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            print_help
            exit 0
            ;;
        -a|--all)
            FILE_PATTERN="*.yaml"
            shift
            ;;
        -d|--dry-run)
            DRY_RUN=1
            shift
            ;;
        -b|--backup)
            BACKUP=1
            shift
            ;;
        -i|--interactive)
            INTERACTIVE=1
            shift
            ;;
        -t|--target)
            TARGET_ACCOUNTS="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        *)
            FILE_PATTERN="$1"
            shift
            ;;
    esac
done

# 如果没有指定文件，默认同步所有
if [ -z "$FILE_PATTERN" ]; then
    FILE_PATTERN="*.yaml"
fi

# 打印标题
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ $DRY_RUN -eq 1 ]; then
    echo -e "${CYAN}  配置文件同步工具 - ${YELLOW}预览模式${NC}"
else
    echo -e "${CYAN}  配置文件同步工具${NC}"
fi
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 显示配置信息
echo -e "${BLUE}📁 源目录:${NC} $SOURCE_DIR"
echo -e "${BLUE}📋 文件模式:${NC} $FILE_PATTERN"
if [ ! -z "$TARGET_ACCOUNTS" ]; then
    echo -e "${BLUE}🎯 目标账户:${NC} $TARGET_ACCOUNTS"
else
    echo -e "${BLUE}🎯 目标账户:${NC} 全部"
fi
if [ $BACKUP -eq 1 ]; then
    echo -e "${BLUE}💾 备份:${NC} ${GREEN}启用${NC}"
fi
echo ""

# 获取匹配的文件列表
FILES=()
for file in $SOURCE_DIR/$FILE_PATTERN; do
    if [ -f "$file" ]; then
        FILES+=("$(basename "$file")")
    fi
done

# 检查是否有匹配的文件
if [ ${#FILES[@]} -eq 0 ]; then
    echo -e "${RED}✗ 没有找到匹配的文件: $FILE_PATTERN${NC}"
    exit 1
fi

# 显示将要同步的文件
echo -e "${YELLOW}📝 将要同步 ${#FILES[@]} 个配置文件:${NC}"
for file in "${FILES[@]}"; do
    echo -e "   • $file"
done
echo ""

# 如果不是预览模式且不是交互模式，询问确认
if [ $DRY_RUN -eq 0 ] && [ $INTERACTIVE -eq 0 ]; then
    echo -e "${YELLOW}? 确认开始同步? (y/n)${NC}"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo -e "${CYAN}✗ 用户取消操作${NC}"
        exit 0
    fi
    echo ""
fi

# 统计计数器
total_files=0
success_count=0
skip_count=0
fail_count=0

# 开始同步
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}开始同步...${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 遍历所有文件
for file in "${FILES[@]}"; do
    echo -e "${BLUE}🔄 处理: $file${NC}"
    
    # 遍历所有目标目录
    for target in "${TARGETS[@]}"; do
        sync_file "$file" "$target"
        result=$?
        
        if [ $result -eq 0 ]; then
            ((success_count++))
        else
            ((fail_count++))
        fi
        ((total_files++))
    done
    
    echo ""
done

# 显示统计信息
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ $DRY_RUN -eq 1 ]; then
    echo -e "${CYAN}预览完成！${NC}"
    echo ""
    echo -e "${BLUE}📊 统计:${NC}"
    echo -e "   • 匹配文件: ${#FILES[@]} 个"
    echo -e "   • 目标账户: ${#TARGETS[@]} 个"
    echo -e "   • 总操作数: $total_files 个"
else
    echo -e "${GREEN}✅ 同步完成！${NC}"
    echo ""
    echo -e "${BLUE}📊 统计:${NC}"
    echo -e "   • 成功: ${GREEN}$success_count${NC} 个"
    if [ $fail_count -gt 0 ]; then
        echo -e "   • 失败: ${RED}$fail_count${NC} 个"
    fi
    echo -e "   • 总计: $total_files 个"
    
    if [ $BACKUP -eq 1 ]; then
        echo ""
        echo -e "${BLUE}💾 备份目录:${NC} $BACKUP_DIR"
    fi
fi
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

