#Allows to exectute the code from the code parameter (multi string parameter)
exec(hou.pwd().parm('code').eval())