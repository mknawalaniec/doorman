import json
import boto3
import requests
import hashlib
import os
import datetime

bucket_name = os.environ['BUCKET_NAME']
slack_token = os.environ['SLACK_API_TOKEN']
slack_channel_id = os.environ['SLACK_CHANNEL_ID']
slack_training_channel_id = os.environ['SLACK_TRAINING_CHANNEL_ID']
recognition_collection_id = os.environ['RECOGNITION_COLLECTION_ID']
dynamodb_users = os.environ['DYNAMODB_USERS']

def guess(event, context):
    try:
        client = boto3.client('recognition')
        key = event['Records'][0]['s3']['object']['key']
        event_bucket_name = event['Records'][0]['s3']['bucket']['name']
        print(event)
        
        if key[-1] == '/':
            print('incoming folder creation detected.')
            return
        
        image = {
            'S3Object': {
                'Bucket': event_bucket_name,
                'Name': key
            }
        }
        print(image)
    
        s3 = boto3.resource('s3')
    
        try:
            resp = client.search_faces_by_image(
                CollectionId=recognition_collection_id,
                Image=image,
                MaxFaces=1,
                FaceMatchThreshold=70)
    
        except Exception as ex:
            # no faces detected, delete image
            print("No faces found, deleting")
            print(ex)
            s3.Object(bucket_name, key).delete()
            return
    
        # if face not recognized at all
        if len(resp['FaceMatches']) == 0:
            # no known faces detected, let the users decide in slack
            print("No matches found, sending to unknown")
            new_key = 'unknown/%s.jpg' % hashlib.md5(key.encode('utf-8')).hexdigest()
            s3.Object(bucket_name, new_key).copy_from(CopySource='%s/%s' % (bucket_name, key))
            s3.ObjectAcl(bucket_name, new_key).put(ACL='public-read')
            s3.Object(bucket_name, key).delete()
            return
        
        # face found!
        print ("Face found")
        print (resp)
        user_id = resp['FaceMatches'][0]['Face']['ExternalImageId']
        similarity = resp['FaceMatches'][0]['Similarity']
        
        # if face similiarity is too low, throw into unmatched
        if int(similarity) < 80:
            # no known faces detected, let the users decide in slack
            print("No matches found, sending to unknown")
            new_key = 'unknown/%s.jpg' % hashlib.md5(key.encode('utf-8')).hexdigest()
            s3.Object(bucket_name, new_key).copy_from(CopySource='%s/%s' % (bucket_name, key))
            s3.ObjectAcl(bucket_name, new_key).put(ACL='public-read')
            s3.Object(bucket_name, key).delete()
            return
        
        # check first, that the user hasn't been recognized within a certain time period
        dynamo = boto3.resource('dynamodb')
        users_table = dynamo.Table(dynamodb_users)
        user_details = users_table.get_item(Key={"id": user_id})
        print(user_details)
        
        # Update last recognized time
        newUpdatedtime = str(datetime.datetime.now())
        users_table.update_item(
            Key={'id': user_id},
            UpdateExpression="set lastRecognizedTime = :t",
            ExpressionAttributeValues={
                ':t': newUpdatedtime
            },
            ReturnValues="UPDATED_NEW"
        )
        
        if 'lastRecognizedTime' in user_details['Item']:
            user_lastRecognizedTime = user_details['Item']['lastRecognizedTime']
        
            print ('check the time diff')
            lastRecognizedTime = datetime.datetime.strptime(user_lastRecognizedTime, "%Y-%m-%d %H:%M:%S.%f")
            print(lastRecognizedTime)
            
            currTime = datetime.datetime.now()
            print(currTime)
            
            difference = currTime - lastRecognizedTime
            print(difference)
            print(difference.seconds)
            print(difference.days)
        
            if difference.seconds < 1200 and difference.days == 0:
                print('user has been recognized within {} minutes, which is under the threshold of 20 minutes.'.format(difference.seconds/60))
                s3.Object(bucket_name, key).delete()
                return
            
        # otherwise, if above threshhold, move to deteched folder and process
        new_key = 'detected/%s/%s.jpg' % (user_id, hashlib.md5(key.encode('utf-8')).hexdigest())
        s3.Object(bucket_name, new_key).copy_from(CopySource='%s/%s' % (event_bucket_name, key))
        s3.ObjectAcl(bucket_name, new_key).put(ACL='public-read')
        s3.Object(bucket_name, key).delete()
    
        # fetch db
        client = boto3.resource('dynamodb')
        table = client.Table(dynamodb_users)
    
        # fetch user information
        user_details = table.get_item(Key={"id": user_id})
        print(user_details)
        user_name = user_details['Item']['name']
        user_email = user_details['Item']['email']
        user_lastEmailedTime = user_details['Item']['lastEmailedTime']

        # alert taining lambda
        # NOTE: To use this function call, you'll need to define an environment variable of TRAIN_API
        #       in serverless.yml and environment.sh, and set the value to the train API uri
        #call_train_lambda(user_id, new_key)
    
        # alert user
        call_slack(user_id, user_name, new_key)
    
        return {}
        
    except Exception as ex:
        print("guess.py encountered an error")
        print(ex)


def call_slack(user_id, user_name, new_key):
    try:
        # alert user
        data = {
            "channel": slack_training_channel_id,
            "text": "Welcome {}! Can we use this new image to better identify you in the future?".format(user_name),
            "attachments": [
                {
                    "image_url": "https://s3.amazonaws.com/%s/%s" % (bucket_name, new_key),
                    "fallback": "Nope?",
                    "callback_id": new_key,
                    "attachment_type": "default",
                    "actions": [
                        {
                            "name": "username",
                            "text": "Yes",
                            "type": "button",
                            "value": user_id
                        },
                        {
                            "name": "discard",
                            "text": "Ignore",
                            "style": "danger",
                            "type": "button",
                            "value": "ignore",
                            "confirm": {
                                "title": "Are you sure?",
                                "text": "Are you sure you want to ignore and delete this image?",
                                "ok_text": "Yes",
                                "dismiss_text": "No"
                            }
                        }
                    ]
                }
            ]
        }
        
        resp = requests.post("https://slack.com/api/chat.postMessage", headers={'Content-Type':'application/json;charset=UTF-8', 'Authorization': 'Bearer %s' % slack_token}, json=data)
        print(resp.json())
        
    except Exception as ex:
        print("guess.py call_slack encountered an error")
        print(ex)
        

def call_train_lambda(user_id, new_key):
    try:
        # alert taining lambda
        payload_content = {
            "type": "interactive_message",
            "actions": [
                {
                    "name": "username",
                    "value": user_id
                }
            ],
            "callback_id": new_key,
            "response_url": ""
        }
        payload = json.dumps(payload_content)
        data = urllib.parse.urlencode( { "payload": payload } )
        
        resp = requests.post(os.environ['TRAIN_API'], headers={'Content-Type':'application/json;charset=UTF-8'}, data=data)
        print(resp)
        
    except Exception as ex:
        print("guess.py call_train_lambda encountered an error")
        print(ex)