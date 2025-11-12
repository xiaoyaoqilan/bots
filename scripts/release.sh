#!/bin/bash
# ============================================================================
# 版本发布脚本
# ============================================================================
# 用法: ./scripts/release.sh v0.1.0 "Release message"
# ============================================================================

set -e  # 遇到错误立即退出

# 检查参数
if [ -z "$1" ]; then
    echo "❌ 错误：请提供版本号"
    echo "用法: ./scripts/release.sh v0.1.0 \"Release message\""
    exit 1
fi

VERSION=$1
MESSAGE=${2:-"Release $VERSION"}

echo "🚀 开始发布版本: $VERSION"
echo ""

# 1. 检查工作区是否干净
if [ -n "$(git status --porcelain)" ]; then
    echo "❌ 错误：工作区有未提交的更改"
    echo "请先提交所有更改后再发布版本"
    exit 1
fi

# 2. 确保在主分支
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "⚠️  警告：当前不在 main 分支 (当前: $CURRENT_BRANCH)"
    read -p "是否继续？(y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 3. 拉取最新代码
echo "📥 拉取最新代码..."
git pull origin $CURRENT_BRANCH

# 4. 更新 VERSION 文件
echo "$VERSION" > VERSION
echo "✅ 已更新 VERSION 文件: $VERSION"

# 5. 提交版本文件
git add VERSION
git commit -m "chore: bump version to $VERSION" || echo "ℹ️  VERSION 文件未变更"

# 6. 推送提交
echo "📤 推送提交..."
git push origin $CURRENT_BRANCH

# 7. 创建标签
echo "🏷️  创建标签: $VERSION"
git tag -a "$VERSION" -m "$MESSAGE"

# 8. 推送标签
echo "📤 推送标签..."
git push origin "$VERSION"

echo ""
echo "✅ 版本 $VERSION 发布成功！"
echo ""
echo "📋 后续步骤："
echo "  1. 访问 GitHub 仓库"
echo "  2. 进入 Releases 页面"
echo "  3. 为标签 $VERSION 创建 Release"
echo "  4. 添加更新日志（从 CHANGELOG.md 复制）"
echo ""
echo "🌐 或者直接访问："
echo "  https://github.com/$(git config --get remote.origin.url | sed 's/.*github.com[:/]\(.*\)\.git/\1/')/releases/new?tag=$VERSION"

