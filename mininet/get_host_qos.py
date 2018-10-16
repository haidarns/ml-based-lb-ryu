import json, glob, sys
from pprint import pprint
import pandas as pd

def extract_qos(filename):
	loss_ls = []
	jitter_ls = []
	sec_ls = []
	with open(filename) as f:
		data = json.load(f)
	conn = data['start']['connected'][0]
	client = conn['remote_host']
	client_name = client.split('.')[-1]
	server = conn['local_host']
	server_name = server.split('.')[-1]
	itrv = data['intervals']
	for stream in itrv:
		loss = stream['sum']['lost_percent']
		jitter = stream['sum']['jitter_ms']
		sec = int(stream['sum']['start'])
		loss_ls.append(loss)
		jitter_ls.append(jitter)
		sec_ls.append(sec)
	col_jitter_name = "h%s_h%s_jitter"%(client_name,server_name)
	col_loss_name = "h%s_h%s_loss"%(client_name,server_name)
	return sec_ls, col_jitter_name, jitter_ls, col_loss_name, loss_ls

def extract_qos_all(output_name):
	files = glob.glob("logfile/*.txt")
	sec_ls, col_jitter_name, col_jitter, col_loss_name, col_loss = extract_qos(files[0])
	df = pd.DataFrame(index=sec_ls, data={col_jitter_name:col_jitter, col_loss_name: col_loss})
	for i in xrange(1, len(files)):
		_, col_jitter_name, col_jitter, col_loss_name, col_loss = extract_qos(files[i])
		df.insert(loc=0, column=col_jitter_name, value=col_jitter)
		df.insert(loc=0, column=col_loss_name, value=col_loss)
	df.sort_index(axis=1, inplace=True)
	df.to_csv('result/qos_%s.csv'%(output_name))

if __name__ == '__main__':
   output_name = sys.argv[1]
   extract_qos_all(output_name)