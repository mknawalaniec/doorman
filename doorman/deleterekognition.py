# Delete all face ids within recognition 
# All users will need to re-register
# To run this, run the lambda explicitly as it is not tied to any triggers

import json
import boto3
import requests
import hashlib
import os

bucket_name = os.environ['BUCKET_NAME']
slack_token = os.environ['SLACK_API_TOKEN']
slack_channel_id = os.environ['SLACK_CHANNEL_ID']
slack_training_channel_id = os.environ['SLACK_TRAINING_CHANNEL_ID']
rekognition_collection_id = os.environ['REKOGNITION_COLLECTION_ID']

def deleterekognition(event, context):
    collectionId=rekognition_collection_id
    maxResults=1000
    tokens=True
    facesIdsToDelete=[]
    
    client=boto3.client('rekognition')
    response=client.list_faces(CollectionId=collectionId,
                               MaxResults=maxResults)

    print('Faces in collection ' + collectionId)

 
    while tokens:

        faces=response['Faces']

        for face in faces:
            print (face)
            facesIdsToDelete.append(face['FaceId'])
        if 'NextToken' in response:
            nextToken=response['NextToken']
            response=client.list_faces(CollectionId=collectionId,
                                       NextToken=nextToken,MaxResults=maxResults)
        else:
            tokens=False

    print('face ids')
    print(facesIdsToDelete)
    
    if len(facesIdsToDelete) > 0:
        responseDelete=client.delete_faces(CollectionId=collectionId,
                               FaceIds=facesIdsToDelete)
    
        print(str(len(responseDelete['DeletedFaces'])) + ' faces deleted:') 							
        for faceId in responseDelete['DeletedFaces']:
             print (faceId)