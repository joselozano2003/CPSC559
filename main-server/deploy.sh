#!/bin/bash
set -e

# Configuration - CHANGE THESE
AWS_REGION=us-west-2  # Your AWS region
REPOSITORY_NAME=maple-quest

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
IMAGE_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPOSITORY_NAME:latest

echo "🔍 AWS Account ID: $AWS_ACCOUNT_ID"
echo "🌍 AWS Region: $AWS_REGION"
echo "📦 Image URI: $IMAGE_URI"

echo "🧹 Cleaning old images and cache..."
docker rmi maple-quest:latest 2>/dev/null || true
docker rmi $IMAGE_URI 2>/dev/null || true
docker builder prune -f

echo "🔨 Building Docker image for linux/amd64..."
docker buildx build \
  --platform linux/amd64 \
  --progress=plain \
  -t maple-quest:latest \
  --load \
  .

echo "🔍 Verifying image architecture..."
ARCH=$(docker inspect maple-quest:latest --format='{{.Architecture}}')
echo "Built architecture: $ARCH"

if [ "$ARCH" != "amd64" ]; then
    echo "❌ ERROR: Image is $ARCH, not amd64!"
    exit 1
fi

echo "✅ Architecture verified: $ARCH"

echo "🔐 Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

echo "🏷️ Tagging image..."
docker tag maple-quest:latest $IMAGE_URI

echo "⬆️ Pushing to ECR..."
docker push $IMAGE_URI

## TODO: Get new CDK names and update below
echo "🚀 Updating ECS service..."
aws ecs update-service \
  --cluster maple-quest-cluster \
  --service MapleQuestStack-MapleQuestServiceE94BCDA4-rA0IAfYpCyFq  \
  --force-new-deployment \
  --region $AWS_REGION

# echo "🛑 Stopping old tasks..."
for task in $(aws ecs list-tasks --cluster maple-quest-cluster --service-name MapleQuestStack-MapleQuestServiceE94BCDA4-rA0IAfYpCyFq --region us-west-2 --query 'taskArns[]' --output text); do
  aws ecs stop-task --cluster maple-quest-cluster --task $task --region us-west-2
done

echo "✅ Deployment complete!"
# echo "🔍 Check logs with: aws logs tail /ecs/maple-quest --follow --region $AWS_REGION"