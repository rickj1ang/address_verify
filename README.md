# address_verify
### pre
你需要准备```gcloud```命令行工具，下载，登陆，用以调用Google Gemini模型，你也可以使用API Key（gcloud是由于香港等地区无法使用API KEY调用）
### install package
```shell
pip install google google.genai
```
### usage
```shell
python workflow.py -p "path/to/address/document"
```
### output
文件夹名：目标地址证明的文件名的hash

- search_result: 联网搜索使用到的网页信息
- output_1.json: 从地址证明文件中识别到的信息
- output_2: 联网搜索到的讯息
- output_3：针对搜索到的讯息，关于地址是否有效的推理
- output_4.json: 最终的判断