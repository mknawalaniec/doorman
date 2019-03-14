# Custom Configuration
export AWS_REGION=us-east-1
export EMAIL_SOURCE=source@email.com
export SLACK_CHANNEL_ID=[channel name]
export SLACK_TRAINING_CHANNEL_ID=[channel name]
export SLACK_API_TOKEN=[oath token]

# General setup
export name=EYH2019-mkn
export QUEUE_NAME=$name-polly
export BUCKET_NAME=$name-images
export RECOGNITION_COLLECTION_ID=$name
export DYNAMODB_USERS=$name-user
export DYNAMODB_INFO=$name-info
export AWS_ACCOUNT_NUMBER=$(curl -s http://169.254.169.254/latest/dynamic/instance-identity/document | jq -r .accountId)
