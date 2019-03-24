# Custom Configuration
export AWS_REGION=us-east-1
export EMAIL_SOURCE=source@email.com
export SLACK_CHANNEL_ID=doorman-eyh
export SLACK_TRAINING_CHANNEL_ID=doorman-eyh
export SLACK_API_TOKEN=xoxp-2151114050-47016907444-586861744086-678ead8f2dcd8081a156a34b8cc0ea59

# General setup
export name=sample-deeplens
export QUEUE_NAME=$name-polly
export BUCKET_NAME=$name-images
export REKOGNITION_COLLECTION_ID=$name
export DYNAMODB_USERS=$name-user
export DYNAMODB_INFO=$name-info
export AWS_ACCOUNT_NUMBER=$(curl -s http://169.254.169.254/latest/dynamic/instance-identity/document | jq -r .accountId)
