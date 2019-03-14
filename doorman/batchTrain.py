import boto3
import uuid
import os
import hashlib
from boto3.dynamodb.conditions import Key, Attr
import random

# bucket with pre-uploaded pictures, filename formatted as "Firstname.Lastname.jpg" and No duplicates
batch_email_domain = "sample.org"
bucket_name = os.environ['BUCKET_NAME']
dynamodb_users = os.environ['DYNAMODB_USERS']
recognition_collection_id = os.environ['RECOGNITION_COLLECTION_ID']
dynamodb_info = os.environ['DYNAMODB_INFO']

def batchTrain(event, context):
	#trainFaces(event, context)
	testing_emotion_data_pull()

# Testing
def testing_emotion_data_pull():
	print('checking emotion and serving up article')
	dynamo = boto3.resource('dynamodb')
	table_info = dynamo.Table(dynamodb_info)

	top_num_articles = 2
	upper_limit = top_num_articles
	
	response = table_info.query(
		KeyConditionExpression=Key('type').eq('fact'),
		ScanIndexForward=False,
        Limit=top_num_articles
    )
    
	if len(response) < top_num_articles:
		upper_limit = response.size
    	
	print(upper_limit)
	random_int = random.randint(0, upper_limit-1)
	most_recent_insights_item = response['Items'][random_int]
	print(most_recent_insights_item)
    
		
	print('done')
	return

# Function will automatically import images for training the model
def trainFaces(event, context):

	# init aws resource clients
	table = boto3.resource('dynamodb').Table(dynamodb_users)
	recClient = boto3.client('recognition')
	s3 = boto3.client('s3')
	s3Resource = boto3.resource('s3')

	# get list of files in bucket
	data = s3.list_objects(Bucket=bucket_name, Delimiter=',', Prefix='batch-training')

	# array for name, email, other data
	people = [];

	# generate data for later use
	for obj in data['Contents']:

		#full filename
		key = obj['Key'].replace("batch-training/","")

		# avoid the folder entry, get the image entries
		if(key.find(".") > 0):
			# get name and generate email
			name = key.split(".")[0] + " " + key.split(".")[1]
			email = key.split(".")[0] + "." + key.split(".")[1] + "@" + batch_email_domain

			people.append({'Key': key, 'Name':name, 'Email':email})

	# run code for saving use in dynamo and train user
	for obj in people:

		key = 'batch-training/%s' % obj['Key']

		# pull off user information
		new_user_name = obj['Name']
		new_user_email = obj['Email']

		# generate unique id
		new_user_id = uuid.uuid4().hex

		# save user details
		
		table.put_item(
		Item= {
		    'id': new_user_id,
		    'name': new_user_name,
		    'email': new_user_email,
		    'lastEmailedTime': 'none'
		    }
		)

		# train the system to recognize the user
		user_id = new_user_id

		new_key = 'trained/%s/%s.jpg' % (user_id, hashlib.md5(key.encode('utf-8')).hexdigest())

		# response is send, start training
		
		resp = recClient.index_faces(
			CollectionId=recognition_collection_id,
			Image={
				'S3Object': {
					'Bucket': bucket_name,
					'Name': key,
				}
			},
			ExternalImageId=user_id,
			#QualityFilter='AUTO',
			DetectionAttributes=['DEFAULT']
		)

		# move the s3 file to the 'trained' location
		s3Resource.Object(bucket_name, new_key).copy_from(CopySource='%s/%s' % (bucket_name, key))
		s3Resource.ObjectAcl(bucket_name, new_key).put(ACL='public-read')
		
	print('done')
	return