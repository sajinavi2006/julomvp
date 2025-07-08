# Authetication header

`{Authorization: Token {token from mvp} }`

or

`{Authorization: JWT {token from auth server} }`



# Login

Used to collect a Token for a registered User.

**URL** : `{auth-server-domain}api/v1/auth/login`

**Method** : `POST`

**Auth required** : NO

**Data constraints**

```json
{
    "username": "[valid email address]",
    "password": "[password in plain text]"
}
```



## Success Response

**Code** : `200 OK`

**Content example**

```json
{"status":"success","data":{"access_token":"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX3hpZCI6ImU0YTJlY2U3LTBiMTItNGE3ZC04OWRkLThlNjI5ODcyOTJhZSIsInJvbGVzIjpbXSwibXZwX3VzZXJfaWQiOiIxMDE0IiwiaXNzdWVfZGF0ZXRpbWUiOiIyMDE4LTA5LTE3IDE5LTEzLTMzLjc4ODY4MiIsImV4cGlyeV9kYXRldGltZSI6IjIwMTgtMDktMTggMTktMTMtMzMuNzg4NjQ4IiwidXNlcm5hbWUiOiJhZ2VubmRkc3pudGs2QGp1bG9maW4uY29tIn0.h2cY7pGBPAS-M9_M0hhjcRD508jOubB2XagEjiQgDlM","expiry_datetime":"2018-09-18 19-13-33.788942","user":{"user_xid":"e4a2ece7-0b12-4a7d-89dd-8e62987292ae","username":"agennddszntk6@julofin.com","first_name":"age11","last_name":"","email":"agennddszntk6@julofin.com"}}}
```

## Error Response

**Condition** : If 'username' and 'password' combination is wrong.

**Code** : `400 BAD REQUEST`


# list agent

used get agent list

**URL** : `/api/v1/agents/`

**arg** : `date-from=2018-09-18&date-to=2018-09-18&role=21&query=search_word`

**Method** : `GET`

**Auth required** : YES
## Success Response

**Code** : `200 OK`

**Content example**

```json
{
    "status": "success",
    "data": 
{
    "count": 5,
    "next": null,
    "previous": null,
    "results": [
        {
            "user": {
                "username": "agentk5@julofin.com",
                "email": "agentk5@julofin.com",
                "first_name": "age11",
                "id": 1008
            },
            "created_by": {
                "username": "ebin123456@gmail.com",
                "email": "ebin123456@gmail.com",
                "first_name": "",
                "id": 11
            },
            "roles": [
                "agent2"
            ],
            "id": 13,
            "user_extension": null,
            "cdate": "2018-09-17T09:26:04.553218Z"
        },
      
    ]
}
}
```

## Error Response
**Code** : `400 BAD REQUEST`


# list role

used get roles

**URL** : `/api/v1/agents/roles`

**Method** : `GET`

**Auth required** : YES

## Success Response

**Code** : `200 OK`

**Content example**

```json
{
    "status": "success",
    "data": 
{
    "count": 3,
    "next": null,
    "previous": null,
    "results": [
        {
            "name": "agent2",
            "id": 21
        },
        {
            "name": "agent3",
            "id": 22
        },
        {
            "name": "agent1",
            "id": 20
        }
    ]
}
}
```

## Error Response
**Code** : `400 BAD REQUEST`



# create agent

used to create an agent

**URL** : `/api/v1/agents`

**Method** : `POST`

**Data constraints**

```json
{
    "user": "[valid email address]",
    "password": "[password in plain text]",
    "name": "[name in plain text]",
    "role": "[role id from roles api]"
   
}
```

**Auth required** : YES

## Success Response

**Code** : `201 OK`

**Content example**

```json
{
    "status": "success",
    "data": 
{
    "message": "created"
}
}
```

## Error Response
**Code** : `400 BAD REQUEST`



# list customers

used get agent list

**URL** : `api/v1/crm/customers`

**arg** : `bucket=t0,t1,t3,t5 etc`, `status=330,331,332`

**Method** : `GET`

**Auth required** : YES
## Success Response

**Code** : `200 OK`

**Content example**

```json
{
    "status": "success",
    "data": {
        "count": 1,
        "next": null,
        "previous": null,
        "results": [
            {
                "id": 1000000001,
                "fullname": "Developer User1",
                "email": "ebin123456@gmail.com",
                "phone": "1234567890",
                "country": "sss",
                "cdate": "2018-08-29T06:45:45.429380Z"
            }
        ]
    }
}
```

## Error Response
**Code** : `400 BAD REQUEST`


# get performance data

used get performance data

**URL** : `api/v1/crm/performance`



**Method** : `GET`

**Auth required** : YES
## Success Response

**Code** : `200 OK`

**Content example**

```json
{
    "status": "success",
    "data": {
        "performance": [],
        "performance_all": [],
        "collection": [
            {
                "fp_np_grace_percent": "0.050",
                "count_payment": null,
                "np_grace_percent": "0.100",
                "np_ontime_percent": "0.165",
                "np_late30_percent": "0.060",
                "fp_np_ontime_percent": "0.100",
                "month_start_date": null,
                "count_first_payment": null
            }
        ]
    }
}
```





