import boto3
import requests
import re
import json, ast
import sys,os
import errno
import pprint

master_json = {
    "AWSTemplateFormatVersion": "2010-09-09",
    "Description": "An AWS Serverless Specification template describing your function.",
    "Resources": {}
}

source_profile="default"
destination_profile="default"

#role = <arn for role>
role ="arn:aws:iam::<account-number>:<rolename>"

#To get more information on using profiles refer below
# https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html
source_session = boto3.session.Session(profile_name=source_profile)
destination_session = boto3.session.Session(profile_name=destination_profile)

def get_account_number(boto_session):
    """
    :param botoSession:
    :return:
    """
    client = boto_session.client("sts")
    account_id = client.get_caller_identity()["Account"]
    return account_id


def get_all_lambda_funtions(lambda_client):
    """
    :param lambda_client:
    :return: List of all Lambda functions related to Handler Ex: {"functionName":"functionARN"}
    """
    try:
        func_arn = {}
        paginator = lambda_client.get_paginator('list_functions')
        for each in paginator.paginate().build_full_result()["Functions"]:
            func_arn[each['FunctionName']] = each["FunctionArn"]
        return func_arn
    except Exception as error:
        print error
        sys.exit(100)


def get_all_regions(BOTO_SESSION):
    """
    :param boto_session:
    :return: list of all regions
    """
    try:
        ec2_client = BOTO_SESSION.client('ec2', region_name="us-east-1")
        all_regions = []
        for each_region in ec2_client.describe_regions()['Regions']:
            # The above code lists all available regions for resource
            all_regions.append(each_region['RegionName'])
        return all_regions
    except Exception as err:
        print err
        return False

def create_dir_if_not_exist(filename):
    """
    :param filename:
    :return:
    """
    if not os.path.exists(os.path.dirname(filename)):
        try:
            os.makedirs(os.path.dirname(filename))
        except OSError as exc:  # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

regions= get_all_regions(destination_session)

print "-----------------AllRegions----------------------"
pprint.pprint(regions)

account_number=get_account_number(destination_session)

print "-----------------Account Number : {} ----------------------".format(account_number)

master_bucket_name = "master-lambda-code-"+str(account_number)
print "-----------------Master Bucket Name : {} ----------------------".format(master_bucket_name)


s3_standard = destination_session.resource('s3','us-east-1')

#     regions.append(each_region['RegionName'])

try:
    s3_standard.create_bucket(Bucket=master_bucket_name)
    print "-----------------Created Master Bucket : {} ----------------------".format(master_bucket_name)
except Exception as err:
    print err


s3_region_client = destination_session.resource('s3')
for each_region in regions:
    print "-----------------Procession Region : {}----------------------".format(each_region)
    child_json = {}
    lambda_client = source_session.client('lambda', each_region)
    functions_dict = get_all_lambda_funtions(lambda_client)
    print "-----------------All Function in region : {}----------------------".format(each_region)
    pprint.pprint(functions_dict.keys())

    # functions_dict = {"GetLambdaFunctionTags":"","ListIAMUserAccessKeys":""}

    region_level_bucket_name = "-".join(["lambdacode",str(each_region),str(account_number)])
    print "-----------------Bucket in {} region is {}----------------------".format(each_region, region_level_bucket_name)
    try:
        # s3_region_client.create_bucket(Bucket=region_level_bucket_name)
        s3_region_client.create_bucket(
            Bucket=region_level_bucket_name,
            CreateBucketConfiguration=
            {
            'LocationConstraint': each_region
            }
        )
        print "-----------------Created Region Bucket : {} ----------------------".format(region_level_bucket_name)
    except Exception as err:
        print err

    for each_function in functions_dict.keys():
        uni_response = lambda_client.get_function(
            FunctionName=each_function
        )
        response = ast.literal_eval(json.dumps(uni_response))
        out = response["Configuration"]
        function_name = out["FunctionName"]
        url = response["Code"]["Location"]
        print "-----------------Downloading the function {} from {} ----------------------".format(each_function, each_region)
        urlresponse = requests.get(url, allow_redirects=True)
        relative_local_file = str(each_region)+"/"+function_name+'.zip'
        #Creates the relative dir
        create_dir_if_not_exist(relative_local_file)
        zipped_file_name=function_name+'.zip'
        print "-----------------Saving file to {}----------------------".format(relative_local_file)
        open(relative_local_file, 'wb').write(urlresponse.content)

        s3_region_client.meta.client.upload_file(relative_local_file, region_level_bucket_name, zipped_file_name)
        print "-----------------uploading file {} to bucket {} ----------------------".format(relative_local_file, region_level_bucket_name)
        s3_standard.meta.client.upload_file(relative_local_file, master_bucket_name, relative_local_file)
        print "-----------------uploading file {} to bucket {} ----------------------".format(relative_local_file,
                                                                                              master_bucket_name)

        #Removes all Non Alphanumeric Characters for creaing resources
        resource_name = re.sub(r'[^a-zA-Z0-9]', "", function_name)
        child_json[resource_name] = {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "Code": {
                    "S3Bucket": region_level_bucket_name,
                    "S3Key": function_name+'.zip'
                },
                "FunctionName": out["FunctionName"],
                "MemorySize": out["MemorySize"],
                "Handler": out["Handler"],
                "Role": role,
                "Timeout": out["Timeout"],
                "Runtime": out["Runtime"],
                "Description": out["Description"],
                # "DeletionPolicy": "Retain"
            }
        }
    if child_json.keys():
        master_json["Resources"] = child_json
        print json.dumps(master_json, indent=4)

        cf_template_name = 'CloudFormationTemplate-'+str(each_region)+'.json'
        with open(cf_template_name, 'w') as f:
            json.dump(master_json, f, indent=4, separators=(',', ': '), sort_keys=True)
            f.write('\n')

        s3_region_client.meta.client.upload_file(cf_template_name, region_level_bucket_name,cf_template_name)
        s3_standard.meta.client.upload_file(cf_template_name, master_bucket_name,str(each_region) + "/" +cf_template_name)
        s3_standard.meta.client.upload_file(cf_template_name, master_bucket_name,cf_template_name)
    else:
        print each_region, "Do not hold any lambda functions"

