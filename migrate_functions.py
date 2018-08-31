import boto3
import requests
import re
import json, ast

master_json = {
    "AWSTemplateFormatVersion": "2010-09-09",
    "Description": "An AWS Serverless Specification template describing your function.",
    "Resources": {}
}

child_json={}

source_profile="default"
destination_profile="default"

#role = <arn for role>
role ="arn:aws:iam::<account-number>:<rolename>"
#Make sure the bucket pre-exist in destination account in the same region as lambda functions
bucket_name = "<bucketname>"
region = 'us-east-1'
list_of_lambda_functions = ['test_function','test_function2']

#To get more information on using profiles refer below
# https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html
source_session = boto3.session.Session(profile_name=source_profile)
destination_session = boto3.session.Session(profile_name=destination_profile)


s3_client = destination_session.resource('s3',region)
lambda_client = source_session.client('lambda', region)



for each_function in list_of_lambda_functions:
    uni_response = lambda_client.get_function(
        FunctionName=each_function
    )
    response = ast.literal_eval(json.dumps(uni_response))
    out = response["Configuration"]
    function_name = out["FunctionName"]
    url = response["Code"]["Location"]
    r = requests.get(url, allow_redirects=True)
    open(function_name+'.zip', 'wb').write(r.content)

    s3_client.meta.client.upload_file(function_name+'.zip', bucket_name, str(function_name)+'.zip'.lower())

    #Removes all Non Alphanumeric Characters for creaing resources
    resource_name = re.sub(r'[^a-zA-Z0-9]', "", function_name)
    child_json[resource_name] = {
        "Type": "AWS::Lambda::Function",
        "Properties": {
            "Code": {
                "S3Bucket": bucket_name,
                "S3Key": function_name+'.zip'
            },
            "FunctionName": out["FunctionName"],
            "MemorySize": out["MemorySize"],
            "Handler": out["Handler"],
            "Role": role,
            "Timeout": out["Timeout"],
            "Runtime": out["Runtime"],
            "Description": out["Description"]
        }
    }
master_json["Resources"] = child_json

print json.dumps(master_json, indent=4)

with open('CloudFormationTemplate.json', 'w') as f:
    json.dump(master_json, f, indent=4, separators=(',', ': '), sort_keys=True)
    f.write('\n')
