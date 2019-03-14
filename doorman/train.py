import json
import boto3
import requests
import hashlib
import os
import datetime
import uuid
from urllib.parse import parse_qs
from boto3.dynamodb.conditions import Key, Attr
import random

bucket_name = os.environ['BUCKET_NAME']
slack_token = os.environ['SLACK_API_TOKEN']
slack_channel_id = os.environ['SLACK_CHANNEL_ID']
rekognition_collection_id = os.environ['REKOGNITION_COLLECTION_ID']
dynamodb_users = os.environ['DYNAMODB_USERS']
dynamodb_info = os.environ['DYNAMODB_INFO']
email_source = os.environ['EMAIL_SOURCE']
polly_queue_name = os.environ['QUEUE_NAME']

class DynamoUser:
    id = 0
    name = ''
    email = ''
    lastEmailedTime = 'none'
    lastRecognizedTime = 'none'

def train(event, context):
    try:
        data = parse_qs(event['body'])
        data = json.loads(data['payload'][0])
        print(data)
        key = data['callback_id']
        
        # Pull off the action
        registered_action = "";
        if "type" in data and data['type'] == "dialog_submission":
            registered_action = "new-user"
        else:
            registered_action = data['actions'][0]['name']
            
        # if we have a register action, send back a json dialog to collect user information
        if registered_action == 'register':
            response_url_curr = data['response_url']
            print('response url before dialog box:')
            print(response_url_curr)
            
            message = {
                "token": slack_token,
                "trigger_id": data["trigger_id"],
                "dialog": json.dumps({
                    "title": "Registration",
                    "callback_id": key,
                    "submit_label": "Submit",
                    #"notify_on_cancel": True,
                    #"state": "",
                    "elements": [
                        {
                            "label": "First Name",
                            "type": "text",
                            "name": "name"
                        }
                        ,{
                            "label": "Email",
                            "type": "text",
                            "subtype": "email",
                            "name": "email"
                        }
                    ]
                })
            }
            print(message)
            
            resp = requests.post("https://slack.com/api/dialog.open", 
                headers={'Content-Type':'application/json;charset=UTF-8', 'Authorization': 'Bearer %s' % slack_token},
                json=message)
            print(resp)
            
            message = {
                "text": "You are in the progress of registering.  If you cancel, you will need to be recognized again to register."
            }
            print(message)
    
            requests.post(
                response_url_curr,
                headers={
                    'Content-Type':'application/json;charset=UTF-8',
                    'Authorization': 'Bearer %s' % slack_token
                },
                json=message
            )
    
        # if we have a register action, send back a json dialog to collect user information
        if registered_action == 'new-user':
            
            # construct new user
            new_user = DynamoUser()
            
            # pull off name
            new_user.name = data['submission']['name']
            
            # pull of email
            new_user.email = 'none'
            if "email" in data['submission']:
                new_user.email = data['submission']['email']
            
            # get table details
            client = boto3.resource('dynamodb')
            table = client.Table(dynamodb_users)
            
            # generate unique id
            new_user.id = uuid.uuid4().hex
            
            # get the current time for when it was last recognized
            new_user.lastRecognizedTime = str(datetime.datetime.now())
            
            # save user details
            table.put_item(
                Item= {
                    'id': new_user.id,
                    'name': new_user.name,
                    'email': new_user.email,
                    'lastEmailedTime': 'none',
                    'lastRecognizedTime': new_user.lastRecognizedTime
                }
            )
            
            # train the system to recognize the user
            train_user(data['response_url'], new_user, key)
    
        # if we got a discard action, send an update first, and then remove the referenced image
        if registered_action == 'discard':
            message = {
                "text": "Ok, I ignored this image."
            }
            print(message)
    
            requests.post(
                data['response_url'],
                headers={
                    'Content-Type':'application/json;charset=UTF-8',
                    'Authorization': 'Bearer %s' % slack_token
                },
                json=message
            )
            s3 = boto3.resource('s3')
            s3.Object(bucket_name, key).delete()
    
        if registered_action == 'username':
            # train on the new photo
            user_id = data['actions'][0]['value']
            user = getUser(user_id)
            train_user(data['response_url'], user, key)
    
    except Exception as ex:
        print("train.py encountered an error")
        print(ex)

    return {
        "statusCode": 200
    }


def train_user(response_url, user, key):
    new_key = 'trained/%s/%s.jpg' % (user.id, hashlib.md5(key.encode('utf-8')).hexdigest())
    
    # response is send, start training
    client = boto3.client('rekognition')
    rekognition_response = client.index_faces(
        CollectionId=rekognition_collection_id,
        Image={
            'S3Object': {
                'Bucket': bucket_name,
                'Name': key,
            }
        },
        ExternalImageId=user.id,
        DetectionAttributes=['ALL']
    )
    print(rekognition_response)
    
    # get emotion details
    emotion_details = get_emotion_details(rekognition_response)
    if emotion_details['emotion'] == "UNKNOWN":
        emotion_text = "\n\nI can't really tell what you're feeling at the moment. "
    else:
        emotion_text = "\n\nYou seem %s. " % (emotion_details['emotion'].lower())
    
    # get 10 most recent news type and choose a random article to present to user
    dynamo = boto3.resource('dynamodb')
    table_info = dynamo.Table(dynamodb_info)

    top_num_articles = 10
    upper_limit = top_num_articles
	
    response = table_info.query(
		KeyConditionExpression=Key('type').eq(emotion_details['type'].lower()),
		ScanIndexForward=False,
        Limit=top_num_articles
    )
    
    print('top 10 articles most recent')
    print(response)
    
    if response['Count'] > 0:
        # if there's less articles than the requested top 10, get all those articles
        if response['Count'] < top_num_articles:
            upper_limit = response['Count']
    
        # accounts for array starting at index 0
        random_int = random.randint(0, upper_limit-1)
        
        most_recent_info_item = response['Items'][random_int]
        emotion_text += "\n\nHere's a {}: {}".format(emotion_details['type'].lower(),most_recent_info_item['description'])
    else:
        print("No {} could be found. Please make sure that there is data entered for that type.".format(emotion_details['type'].lower()))
        
    # drop greeting onto an SQS queue
    sqs = boto3.resource(service_name='sqs', region_name='us-east-1')
    greeting_text = getIceBreakerQuestion()
    polly_queue = sqs.get_queue_by_name(QueueName=polly_queue_name)    
    polly_queue.send_message(MessageBody="Hello %s! %s" % (user.name, greeting_text))
    
    # move the s3 file to the 'trained' location
    s3 = boto3.resource('s3')
    s3.Object(bucket_name, new_key).copy_from(CopySource='%s/%s' % (bucket_name, key))
    s3.ObjectAcl(bucket_name, new_key).put(ACL='public-read')
    s3.Object(bucket_name, key).delete()
    
    # post slack reply
    if response_url:
        message = {
            "response_type": "in_channel",
            "text": "Thank you! Your new picture was successfully imported into the recognition engine. %s" % emotion_text,
            "attachments": [
                {
                    "image_url": "https://s3.amazonaws.com/%s/%s" % (bucket_name, new_key),
                    "fallback": "Nope?",
                    "attachment_type": "default",
                }
            ]
        }
        print(message)
        requests.post(response_url, headers={'Content-Type':'application/json;charset=UTF-8', 'Authorization': 'Bearer %s' % slack_token}, json=message)
    
    # Send email
    #send_email(user)

def send_email(user):
    # fetch db
    client = boto3.resource('dynamodb')
    
    should_send_email = True
    
    if user.lastEmailedTime != 'none':
        print ('check the time diff')
        lastEmailedTime = datetime.datetime.strptime(user.lastEmailedTime, "%Y-%m-%d %H:%M:%S.%f")
        print(lastEmailedTime)
        
        currTime = datetime.datetime.now()
        print(currTime)
        
        difference = currTime - lastEmailedTime
        print(difference)
        
        #update this to 1 after done testing
        print(difference.days)
        if difference.days < 1:
            should_send_email = False
        
    if should_send_email:
        table_info = client.Table(dynamodb_info)
        client = boto3.client('ses')
    
        response = table_info.query(
            KeyConditionExpression=Key('type').eq('news'),
            ScanIndexForward=False,
        )
        
        most_recent_news_item = response['Items'][0]
        
        print(most_recent_news_item)
            
        try:
            response = client.send_email(
                Destination = { 'ToAddresses': [user.email] },
                Message = {
                    'Body': {
                        'Text': {
                            'Charset': 'UTF-8',
                            'Data': "Hello {}, \n\n Here is your most recent news news:\n\n{}".format(user.name, most_recent_news_item['description']),
                        },
                    },
                    'Subject': {
                        'Charset': 'UTF-8',
                        'Data': "Your Daily News",
                    },
                },
                Source = email_source
            )
    
            print(response)
            
            newUpdatedtime = str(datetime.datetime.now())
            
            table = client.Table(dynamodb_users)
            response = table.update_item(
                Key={'id': user.id},
                UpdateExpression="set lastEmailedTime = :t",
                ExpressionAttributeValues={
                    ':t': newUpdatedtime
                },
                ReturnValues="UPDATED_NEW"
            )
            print(response)
            
            #update last email time in users table
        except Exception as ex:
            print('email failed sending')
            print(ex)


def get_emotion_details(rekognition_response):
    # docs: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rekognition.html#Rekognition.Client.index_faces
    # process image attributes
    try:
        # pull off emotions details
        face_detail = rekognition_response['FaceRecords'][0]['FaceDetail']
        
        # find emotion with highest confidence
        emotion = "UNKNOWN"
        emotion_confidence = 0
        for obj in face_detail['Emotions']:
            if obj['Confidence'] > emotion_confidence:
            	emotion = obj['Type']
            	emotion_confidence = obj['Confidence']
            	
        # find type of data to serve up
        emotion_response_type = 'FACT'
        if emotion_confidence > 55 and (emotion == 'HAPPY' or emotion == 'CALM' or emotion == 'SURPRISED'):
        	emotion_response_type = 'QUOTE'
        elif emotion_confidence > 55 and (emotion == 'SAD' or emotion == 'ANGRY' or emotion == 'DISGUSTED'):
        	emotion_response_type = 'JOKE'
    	
    	# return collected data
        return {
    		'emotion': emotion,
    		'confidence': emotion_confidence,
    		'type': emotion_response_type
        }
        
    except Exception as ex:
        print("unable to parse face details")
        print(ex)
        return {
            'emotion': 'UNKNOWN',
            'confidence': 0,
            'type': 'FACT'
        }

def getIceBreakerQuestion():
    iceBreakers = ["What is your favorite animal?",
                    "What is your favorite food?",
                    "What is your favorite movie or TV show?",
                    "Who is one of your favorite singers or bands?",
                    "What is your dream job?"]
    
    count = iceBreakers['Count']
    
    # accounts for array starting at index 0
    random_int = random.randint(0, count-1)
    
    return iceBreakers[random_int]
        
def getUser(user_id):
    # fetch db
    client = boto3.resource('dynamodb')
    table = client.Table(dynamodb_users)

    # fetch user information
    user_details = table.get_item(Key={"id": user_id})
    print(user_details)
    
    # construct object
    user = DynamoUser()
    user.id = user_id
    user.name = user_details['Item']['name']
    user.email = user_details['Item']['email']
    user.lastEmailedTime = user_details['Item']['lastEmailedTime']
    user.lastRecognizedTime = user_details['Item']['lastRecognizedTime']
    
    return user