HAP 组织授权开放接口为每个组织提供一套独立的密钥信息（AppKey 和 SecretKey），组织可通过此密钥信息安全调用 HAP 平台开放的各类接口，包括人员组织管理、汇报关系管理、应用管理、流程待办等数据接口。该授权体系具备较高的数据读取权限，密钥信息仅限企业管理员查看与管理，确保数据安全与访问合规。

# 组织授权签名

- 进入 HAP 系统，依次进入 **组织管理** 》 **集成** 》 **其他** 》 **组织密钥**，获取组织授权开放接口的密钥对信息
- 获取当前 Unix 时间戳（单位：毫秒），此时间戳将在调用数据接口时作为必需参数传递
- 将密钥对中的 AppKey、SecretKey 和获取的 Unix 时间戳以键值对的形式拼接成字符串，格式为：`AppKey=value1&SecretKey=value2&Timestamp=value3`
- 使用 SHA256 算法对拼接的字符串进行加密，随后将加密结果进行 BASE64 编码，即可生成最终签名
- 签名生成后 1h 内有效

# 基础参数说明

|参数名|必选|类型|说明|
|:----    |:---|:----- |-----   |
|appKey|是|string|AppKey|
|sign|是|string|签名，参考[组织授权签名](#section/组织授权签名)|
|timestamp|是|long|Unix时间戳（与签名所用时间戳一致，精度为毫秒）|
|projectId|是|string|组织编号|

# 签名算法参考

<div class="codeSample">

<details>
<summary>C#</summary>

```
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Security.Cryptography;

namespace Utility
{
    public static class Signature
    {
        /// <summary>
        /// Generates a signature using SHA-256 hashing algorithm
        /// </summary>
        /// <param name="appKey">Application key</param>
        /// <param name="secretKey">Secret key for encryption</param>
        /// <param name="timestamp">UTC timestamp in milliseconds</param>
        /// <returns>Base64 encoded signature string</returns>
        public static string GetSignature(string appKey, string secretKey, long timestamp)
        {
            var parameters = new Dictionary<string, string>
            {
                ["AppKey"] = appKey,
                ["SecretKey"] = secretKey,
                ["Timestamp"] = timestamp.ToString()
            };

            string sortedParameters = GetSortedParameters(parameters);
            string hash = ComputeSHA256Hash(sortedParameters);
            
            return Convert.ToBase64String(Encoding.UTF8.GetBytes(hash));
        }

        public static string ComputeSHA256Hash(string input)
        {
            using (var sha256 = SHA256.Create())
            {
                byte[] hashedBytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(input));
                return BitConverter.ToString(hashedBytes).Replace("-", "").ToLower();
            }
        }

        public static string GetSortedParameters(Dictionary<string, string> parameters)
        {
            var sb = new StringBuilder();
            
            foreach (var item in parameters.OrderBy(p => p.Key))
            {
                sb.Append($"&{item.Key}={item.Value}");
            }

            return sb.Length > 0 ? sb.ToString(1, sb.Length - 1) : string.Empty;
        }
    }
}
```
</details>

<details>
<summary>Java</summary>

```
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;
import java.util.Base64;

public class Signature {

    /**
    * Generates signature using SHA-256 hash and Base64 encoding
    *
    * @param appKey     Application key
    * @param secretKey  Secret key for encryption
    * @param timestamp  UTC timestamp in milliseconds
    * @return           Generated signature string
    * @throws Exception If any error occurs during signature generation
    */
    public static String getSignature(String appKey, String secretKey, Long timestamp) throws Exception {
        // Prepare parameters map
        Map<String, String> params = new HashMap<>();
        params.put("AppKey", appKey);
        params.put("SecretKey", secretKey);
        params.put("Timestamp", timestamp.toString());

        // Sort parameters by key using TreeMap
        Map<String, String> sortedParams = new TreeMap<>(params);

        // Build query string from sorted parameters
        StringBuilder queryStringBuilder = new StringBuilder();
        Iterator<String> it = sortedParams.keySet().iterator();
        
        if (it.hasNext()) {
            String key = it.next();
            queryStringBuilder.append(key).append("=").append(params.get(key));
        }
        
        while (it.hasNext()) {
            String key = it.next();
            queryStringBuilder.append("&").append(key).append("=").append(params.get(key));
        }

        String sortedQueryString = queryStringBuilder.toString();
        String sha256Hash = sha256(sortedQueryString);
        
        // Encode to Base64 and remove any line breaks
        return Base64.getEncoder().encodeToString(sha256Hash.getBytes("UTF-8"))
                    .replace("\n", "").replace("\r", "");
    }

    private static String sha256(final String text) throws Exception {
        if (text == null || text.isEmpty()) {
            return null;
        }

        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hashBytes = digest.digest(text.getBytes("UTF-8"));

        StringBuilder hexString = new StringBuilder();
        for (byte b : hashBytes) {
            String hex = Integer.toHexString(0xff & b);
            if (hex.length() == 1) {
                hexString.append('0');
            }
            hexString.append(hex);
        }

        return hexString.toString();
    }
}
```
</details>


<details>
<summary>Go</summary>

```
package main

import (
    "crypto/sha256"
    "encoding/base64"
    "encoding/hex"
    "fmt"
    "time"
)

func main() {
    ti := time.Now().UnixNano() / 1e6 // UTC timestamp in milliseconds
    sign := GetSignature("appKey", "secretKey", ti)
    fmt.Println(sign)
}

func GetSignature(appKey, secretKey string, timestamp int64) string {
    // Create the key string for hashing
    key := fmt.Sprintf("AppKey=%s&SecretKey=%s&Timestamp=%d", appKey, secretKey, timestamp)
    
    // Calculate SHA256 hash
    hash := sha256.Sum256([]byte(key))
    
    // Convert hash to hexadecimal string
    hexKey := hex.EncodeToString(hash[:])
    
    // Encode the hex string in base64 and return
    return base64.StdEncoding.EncodeToString([]byte(hexKey))
}
```
</details>

<details>
<summary>Python</summary>

```
import hashlib
import base64

# timestamp: UTC timestamp in milliseconds
def get_signature(app_key: str, app_secret: str, timestamp: int) -> str:
    # Create and sort the parameter dictionary
    params = {
        "AppKey": app_key,
        "SecretKey": app_secret,
        "Timestamp": str(timestamp)
    }
    sorted_params = sorted(params.items(), key=lambda item: item[0])
    
    # Build the signature string by joining key-value pairs
    signature_str = '&'.join([f"{key}={value}" for key, value in sorted_params])
    
    # Generate SHA-256 hash
    sha = hashlib.sha256()
    sha.update(signature_str.encode("utf-8"))
    
    # Return Base64 encoded hex digest
    return base64.b64encode(sha.hexdigest().encode("utf-8")).decode("utf-8")
```
</details>

<details>
<summary>PHP</summary>

```
<?php

function getSignature($appKey, $secretKey, $timestamp) {
    $tempdata = array(
        "AppKey" => $appKey,
        "SecretKey" => $secretKey,
        "Timestamp" => strval($timestamp)
    );
    $signstr = '';
    $keys = array_keys($tempdata);
    sort($keys);
    foreach ($keys as $value) {
        $signstr = $signstr . '&' . $value . '=' . $tempdata[$value];
    }
    $signstr = substr($signstr, 1);
    return base64_encode(hash("sha256", $signstr));
}

?> 
```
</details>

<details>
<summary>Nodejs</summary>

```
const crypto = require('crypto');
const _ = require('lodash');

/**
* Generate signature for authentication
* @param {string} appKey - Application key
* @param {string} secretKey - Secret key
* @param {number} timestamp - UTC timestamp in milliseconds
* @returns {string} - Base64 encoded SHA256 signature
*/
function getSignature(appKey, secretKey, timestamp) {
    const tempData = {
        "AppKey": appKey,
        "SecretKey": secretKey,
        "Timestamp": timestamp.toString()
    };
    
    // Sort keys alphabetically and concatenate key-value pairs
    const signStr = _(tempData)
        .keys()
        .sort()
        .map(key => `${key}=${tempData[key]}`)
        .join('&');
    
    return hashAndEncode(signStr);
}

function hashAndEncode(str) {
    const hash = crypto.createHash('sha256')
        .update(str, 'utf8')
        .digest('hex')
        .toLowerCase();
    
    return Buffer.from(hash, 'utf8').toString('base64');
}

```
</details>

</div>