# Azure function to scrape session protocol documents from kantonsrat.zh.ch

The following components are central for the azure function: 

- `Dockerfile`: Dockerfile for installing selenium and other dependencies in the docker container.
- `requirements.txt`: Python libraries that should be pip installed in the docker container.
- `scrape_kantonsrat/function.json`: Configuration of the azure function. (Contains the scheduling information.)
- `scrape_kantonsrat/__init__.py`: Effective python code that is executed in the azure function.

