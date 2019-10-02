import datetime
import os
import shutil
import smtplib
from smb.SMBConnection import SMBConnection


class SendData(object):

    def __init__(self, context):
        self.context = context
        # self.meta = self.context["meta"]
        self.logger = self.context["logger"]
        self.app_conn = self.context["app_conn"]

    # delivery data file to end customer
    def delivery_file(self, meta_data, src_file):
        _delivery_type = meta_data.DELIVERY_TYPE.split(',')   # rsi/customer/email
        _dst_folder = meta_data.EXTRACTION_FOLDER
        _username = meta_data.USERNAME
        _password = meta_data.PASSWORD

        if "customer" in str(_delivery_type).lower():
            self.logger.info("Sending file: %s into dest folder: %s" % (src_file, _dst_folder))
            self.send_to_folder(filename=src_file, dst_folder=_dst_folder, username=_username, password=_password)

        if "rsi" in str(_delivery_type).lower():
            _cust_ftp_server = meta_data.SERVER
            self.send_to_ftp(filename=src_file, dst_folder=_dst_folder,
                             ftp_server=_cust_ftp_server, username=_username, password=_password)

        if "email" in str(_delivery_type).lower():
            self.logger.warning("Email delivery is not supported yet!!!")
            _mail_account = _username
            _smtp_server = meta_data.SERVER
            _mail_subj = meta_data.MAIL_SUBJECT
            _mail_body = meta_data.MAIL_BODY
            _mail_cc = meta_data.MAIL_RECPSCC
            _mail_to = meta_data.MAIL_RECPSTO
            mail_params = dict(
                mail_server=_smtp_server,
                mail_from=_username,
                mail_subject=_mail_subj,
                mail_body=_mail_body,
                mail_recpsto=_mail_to,
                mail_recpscc=_mail_cc,
                mail_type="html",
                attachment=src_file
            )
            # self.send_mail(mail_params=mail_params, conn=self.app_conn)

        self.logger.info("Alert delivery is done for file: %s" % src_file)

    def send_to_folder(self, filename, dst_folder, username=None, password=None):
        """
        This method is to send file to pre-config place. e.g. shared folder.

        :param filename:
        :param dst_folder:
        :param username:
        :param password:
        :return:
        """
        self.logger.debug("The destination folder is: %s" % dst_folder)

        if os.name == "posix":
            sep = os.sep
            dst_folder_slash = str(dst_folder).replace("\\", sep)  # convert the \ to / if any to align up.
            self.logger.debug("The converted destination folder is: %s" % dst_folder_slash)

            file_basename = os.path.basename(filename)
            server, driver, share_path = self._splitdrive(dst_folder_slash)
            self.logger.debug("Server is: %s, driver is: %s, path is: %s" % (server, driver, share_path))

            # server_ip = "10.172.43.99"        # as must this
            server_ip = server  # as must this
            server_machine_name = server  # MUST match correctly
            local_machine_name = "alerts_delivery"  # arbitrary
            share_name = driver

            conn = SMBConnection(username, password, local_machine_name, server_machine_name, use_ntlm_v2=True)
            assert conn.connect(server_ip, 139)
            with open(filename, 'rb') as file_obj:
                # path has to be the file name under shared folder.
                conn.storeFile(share_name, str(share_path) + sep + file_basename, file_obj)

            conn.close()

        elif os.name == "nt":
            if not os.path.isdir(dst_folder):
                self.logger.error("dst %s is not a directory or not accessible" % dst_folder)
            else:
                shutil.copy(src=filename, dst=dst_folder)
                self.logger.info("moved file to :%s successfully" % dst_folder)

        else:
            self.logger.warning("unknown system!")

    def send_to_ftp(self, filename, dst_folder, ftp_server=None, username=None, password=None):
        """
        There could be a internal FTP folder which we can utilize. Then this will be similar to send_file.
        So we can just call send_file. the only difference for send_file and send_ftp is the dst_folder.

        :param filename:
        :param dst_folder:
        :param ftp_server:
        :param username:
        :param password:
        :return:
        """
        # TODO: this is pending here while this is no API to get the ftp info.
        self.send_to_folder(filename, dst_folder, username, password)

    def send_to_mail(self, mail_params, conn=None):
        """
        This is a generic way of sending mail for python. as long as pass related parameters.
        the mail_params is a dictionary which contains following elements for email sending.

        :param mail_params:
        :param conn
        :return:
        """

        # if conn not passed or file size is bigger than 1 MB. Then send mail via python
        if conn is None or round(os.path.getsize(mail_params["attachment"])/1024/1024) > 1:
            self.send_mail_python(mail_params)
        else:
            self.send_mail_mssql(conn, mail_params)

    def _splitdrive(self, p):
        """
        spliting path p into server + driver + path
        :param p: p = server + driver + path
        :return:
        """
        if len(p) >= 2:
            if isinstance(p, bytes):
                sep = b'\\'
                altsep = b'/'
                colon = b':'
            else:
                sep = '\\'
                altsep = '/'
                colon = ':'
            normp = p.replace(altsep, sep)
            if (normp[0:2] == sep * 2) and (normp[2:3] != sep):
                # is a UNC path: \\machine\mountpoint\directory\etc\...
                index = normp.find(sep, 2)
                if index == -1:  # e.g. \\machine
                    # return p[:0], p[:0], p  # ("", "", "\\machine")
                    self.logger.error("The shared path: %s seems too short." % p)

                index2 = normp.find(sep, index + 1)
                # a UNC path can't have two slashes in a row
                # (after the initial two)
                if index2 == index + 1:  # 2 slashes after the initial two. e.g. \\machine\\mountpoint
                    # return p[:0], p[:0], p  # ("", "", "\\machine\\mountpoint")
                    self.logger.error("The shared path: %s seems having 2 slashes after the initial 2." % p)
                if index2 == -1:  # no more path found. e.g. \\machine\mountpoint
                    index2 = len(p)
                return p[2:index], p[index + 1:index2], p[index2:]
            if normp[1:2] == colon:
                self.logger.error("The path: %s is not an UNC path." % p)
        self.logger.error("The shared path: %s seems wrong." % p)

    # todo: mail account info required
    def send_mail_python(self, mail_params):
        mail_from = mail_params["mail_from"]
        mail_to = mail_params["mail_recpsto"]
        mail_cc = mail_params["mail_recpscc"]
        mail_subject = mail_params["mail_subject"]
        mail_body = mail_params["mail_body"]
        mail_type = mail_params["mail_type"]
        report_filename = mail_params["attachment"]
        # _smtp_server = ""
        # server = smtplib.SMTP(_smtp_server, 25)
        # pwd = ""
        # server.login(mail_from, pwd)
        # server.sendmail(mail_from, mail_to, mail_body)
        # server.quit()

    # dbo.sp_send_dbmail can be disabled in MSSql as below. So we need a alternative way of sending mail.
    @DeprecationWarning
    def send_mail_mssql(self, mssql_conn, mail_params):
        """
        This method is utilizing mssql sp exec msdb.dbo.sp_send_dbmail to send mail. This is only used when sending mail via MSSQL

        Noted: File attachment or query results size SHOULD NOT exceeds allowable value of 1000000 bytes.

        :param mssql_conn:
        :param mail_params:
        :return:
        """
        conn = mssql_conn
        mail_to = mail_params["mail_recpsto"]
        mail_cc = mail_params["mail_recpscc"]
        mail_subject = mail_params["mail_subject"]
        mail_body = mail_params["mail_body"]
        mail_type = mail_params["mail_type"]
        attachment = mail_params["attachment"]

        timestamp = datetime.datetime.now().strftime('%Y%m%d')

        s_mail = """
        declare @Msg            nvarchar(max)
        declare @Type           nvarchar(16)   = '{type}' 
        declare @RecpsTo        nvarchar(4000) = '{recpsto}'
        declare @RecpsCC        nvarchar(4000) = '{recpscc}'
        declare @Subject        nvarchar(255)  = '{subject}'
        declare @body           nvarchar(max)  = 'select ''{mail_body}'''
        declare @TimeStamp      varchar(26)    = '{timestamp}'
        declare @ReportFileName nvarchar(256)  = '{reportfilename}'
        declare @TmpTbl         table(A nvarchar(max))
    
        if (@Subject is not null or @Body is not null) begin
            set @Msg = 'Start Sending Dump File to User for file type: @Type'
            print @Msg
    
            if (@RecpsTo is null)begin
                SELECT @Msg = 'Require to configure the column `"EMAIL_RECPSTO`" in the table dbo.ANL_META_DUMPFILES for sending the dump file' 
                print @Msg
                return
            end
    
            set @Body = REPLACE(@Body,'{timestamp}',convert(date,@TimeStamp,120))
            set @Subject = REPLACE(@Subject,'{timestamp}',convert(date,@TimeStamp,120))
    
            -- @Body include a query string,Execute query and place the query result into TmpTbl(A)
            begin try
                delete from @TmpTbl
                insert into @TmpTbl (A)
                    exec (@Body)
            end try
            begin catch
                set @Msg = N'Failed to build the email body by using query '+@Body+N',please check the detail error msg :'+ERROR_MESSAGE()
                print @Msg
                return
            end catch
    
            -- get the real body info from TmpTbl(A)
            select top 1  @Body = A from @TmpTbl
    
            if (@Body is null)begin
                select @Msg = 'Require to correct configuration for the column `"EMAIL_BODY`" in the table dbo.ANL_META_DUMPFILES for sending the dump file' 
                print @Msg
                return
            end
    
            begin try
                exec msdb.dbo.sp_send_dbmail 
                    @recipients = @RecpsTo,
                    @copy_recipients = @RecpsCC,
                    @Subject = @Subject, 
                    @body = @Body, 
                    @body_format = 'HTML',
                    @file_attachments = @ReportFileName;
    
                set @Msg = 'End Sending Dump File to User for file type:"'+isnull(@Type,'')+'"'
                print @Msg
            end try
            begin catch
                set @Msg = 'Failed to send email to user,please check the detail error msg :'+ERROR_MESSAGE()
                print @Msg
                return
            end catch
    
            waitfor delay '00:00:02'
        end """.format(type=mail_type,
                       recpsto=mail_to,
                       recpscc=mail_cc,
                       subject=mail_subject,
                       mail_body=mail_body,
                       timestamp=timestamp,
                       reportfilename=attachment)
        self.logger.info(s_mail)
        conn.execute(s_mail)
